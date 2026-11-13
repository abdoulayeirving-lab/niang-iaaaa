# voice_activation.py
# NIANG IA — background voice activation ("Hey Niang" / "Niang IA").
#
# Local + free detection, two engines, first available wins:
#   1. Custom openWakeWord model (models/hey_niang_v0.1.onnx — trainable via
#      the existing "record/train the wake word" voice flow).
#   2. Vosk offline keyword spotting (no training needed; the small French
#      model is downloaded once into models/vosk/ and then runs fully local).
#
# The listener runs its own hardened microphone loop (auto-restart with
# backoff, device-change handling, refractory cooldown against accidental
# activations) and never touches the Gemini session or the UI thread.

import json
import threading
import time
import zipfile
from collections import deque
from pathlib import Path

import numpy as np
import sounddevice as sd

BASE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = BASE_DIR / "config"
SETTINGS_PATH = CONFIG_DIR / "app_settings.json"
MODELS_DIR = BASE_DIR / "models"

RATE = 16000
CHANNELS = 1
CHUNK = 1280                     # 80 ms @16 kHz
DEVICE_CHECK_INTERVAL = 4.0      # seconds between default-device checks

WAKE_PHRASES = ("Hey Niang", "Niang IA")
CUSTOM_MODEL_CANDIDATES = ("hey_niang_v0.1.onnx", "hey_kaizumi_v0.1.onnx")

DEFAULT_SETTINGS = {
    "wake_word_enabled": True,     # permanent listening can be disabled here
    "wake_threshold": 0.6,         # openWakeWord score threshold
    "refractory_seconds": 3.0,     # min delay between two activations
    "background_alpha": 1.0,       # 1.0 = opaque, 0.88 = semi-transparent
}

VOSK_DIR = MODELS_DIR / "vosk"
VOSK_MODEL_NAME = "vosk-model-small-fr-0.22"
VOSK_URL = "https://alphacephei.com/vosk/models/vosk-model-small-fr-0.22.zip"
VOSK_KEYWORDS = ["niang", "hey niang", "niang ia"]


# ── Settings (config/app_settings.json) ─────────────────────────────────────

def load_settings() -> dict:
    data = dict(DEFAULT_SETTINGS)
    try:
        loaded = json.loads(SETTINGS_PATH.read_text(encoding="utf-8-sig"))
        if isinstance(loaded, dict):
            for key in DEFAULT_SETTINGS:
                if key in loaded:
                    data[key] = loaded[key]
    except (OSError, json.JSONDecodeError):
        pass
    return data


def save_settings(patch: dict) -> dict:
    settings = load_settings()
    for key, value in (patch or {}).items():
        if key in DEFAULT_SETTINGS:
            settings[key] = value
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(
            json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as e:
        print(f"[VoiceActivation] ⚠️ settings save failed: {e}")
    return settings


def update_setting(key: str, value) -> dict:
    return save_settings({key: value})


# ── Shared robust microphone loop ───────────────────────────────────────────

def _default_input_index():
    try:
        info = sd.query_devices(kind="input")
    except Exception:
        return None
    if not isinstance(info, dict):
        return None
    index = info.get("index")
    return index if isinstance(index, int) and index >= 0 else None


class _MicEngine:
    """Base engine: one background thread owning a resilient mic stream."""

    name = "base"

    def __init__(self):
        self._running    = False
        self._thread     = None
        self._on_detect  = None
        self._on_status  = None   # optional logger: callable(str) -> None
        self._on_level   = None   # optional mic level: callable(0..1) -> None
        self._last_device = None

    # -- subclasses implement ----------------------------------------------
    @property
    def available(self) -> bool:
        return False

    def _setup(self) -> str:
        """Prepare the detector. Return '' on success or an error message."""
        return ""

    def _process(self, block: np.ndarray):
        """Consume one int16 mono 16 kHz chunk."""
        raise NotImplementedError

    def _teardown(self):
        pass

    # -- plumbing ------------------------------------------------------------
    def _notify(self, message: str):
        if self._on_status:
            try:
                self._on_status(f"[{self.name}] {message}")
            except Exception:
                pass

    def configure(self, on_detect=None, on_status=None, on_level=None):
        self._on_detect = on_detect
        self._on_status = on_status
        self._on_level  = on_level

    @property
    def running(self) -> bool:
        return self._running

    def start(self, on_detect=None, on_status=None, on_level=None) -> str:
        if self._running:
            return "Écoute vocale déjà active."
        self.configure(on_detect, on_status, on_level)
        error = self._setup()
        if error:
            return error
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name=f"WakeLoop-{self.name}")
        self._thread.start()
        return f"Écoute vocale active ({' / '.join(WAKE_PHRASES)} — moteur {self.name})."

    def stop(self) -> str:
        if not self._running:
            return "Écoute vocale déjà arrêtée."
        self._running = False
        thread = self._thread
        self._thread = None
        if thread:
            thread.join(timeout=4)
        self._teardown()
        return "Écoute vocale arrêtée."

    def _loop(self):
        retry = 1.0
        while self._running:
            try:
                with sd.InputStream(
                    samplerate=RATE, channels=CHANNELS, dtype="int16",
                    blocksize=CHUNK, callback=self._callback,
                ) as stream:
                    device = stream.device
                    self._last_device = (
                        device.get("index") if isinstance(device, dict) else device
                    )
                    self._notify("microphone ouvert — écoute en cours")
                    retry = 1.0
                    last_device_check = time.monotonic()
                    while self._running:
                        time.sleep(0.4)
                        if not stream.active:
                            raise RuntimeError("flux microphone inactif")
                        if time.monotonic() - last_device_check > DEVICE_CHECK_INTERVAL:
                            current = _default_input_index()
                            if (current is not None and self._last_device is not None
                                    and current != self._last_device):
                                self._last_device = current
                                raise RuntimeError("microphone par défaut changé")
                            last_device_check = time.monotonic()
            except Exception as exc:
                if not self._running:
                    break
                self._notify(f"microphone : {exc} — relance dans {retry:.0f}s")
                time.sleep(retry)
                retry = min(retry * 2, 10)

    def _callback(self, indata, frames, time_info, status):
        if self._running:
            try:
                if self._on_level:
                    rms = float(np.sqrt(np.mean(indata.astype(np.float32) ** 2)))
                    self._on_level(min(1.0, rms / 3000.0))
            except Exception:
                pass
            try:
                self._process(indata.copy())
            except Exception as exc:
                self._notify(f"erreur de détection : {exc}")


# ── Engine 1: openWakeWord custom model (Hey Niang / Niang IA) ──────────────

class OwwWakeEngine(_MicEngine):

    name = "openwakeword"

    def __init__(self, model_file: str):
        super().__init__()
        self.model_file = model_file
        self._model = None
        self._buffer: list[np.ndarray] = []
        self._buffer_lock = threading.Lock()
        self._threshold = 0.6
        self._oww = None

    @property
    def available(self) -> bool:
        if not (MODELS_DIR / self.model_file).exists():
            return False
        if self._oww is None:
            try:
                from openwakeword.model import Model
                self._oww = Model
            except Exception:
                self._oww = False
        return self._oww is not None

    def _setup(self) -> str:
        try:
            self._model = self._oww(
                wakeword_model_paths=[str(MODELS_DIR / self.model_file)])
        except Exception as exc:
            self._model = None
            return f"chargement du modèle impossible : {exc}"
        with self._buffer_lock:
            self._buffer.clear()
        return ""

    def _process(self, block: np.ndarray):
        if self._model is None:
            return
        with self._buffer_lock:
            self._buffer.append(block)
            if len(self._buffer) > 15:
                self._buffer.pop(0)
            audio = np.concatenate(self._buffer)
        predictions = self._model.predict(audio)
        stem = Path(self.model_file).stem
        keys = {stem}
        if stem.startswith("hey_"):
            keys.add(stem[4:])
        score = max((predictions.get(k, 0.0) for k in keys), default=0.0)
        if score >= self._threshold:
            with self._buffer_lock:
                self._buffer.clear()
            self._notify(f"détection (score {score:.2f})")
            self._fire()

    def _teardown(self):
        self._model = None

    def _fire(self):
        if self._on_detect:
            try:
                self._on_detect()
            except Exception as exc:
                self._notify(f"erreur de callback : {exc}")


# ── Engine 2: Vosk offline keyword spotting (works without training) ────────

class VoskWakeEngine(_MicEngine):

    name = "vosk"

    def __init__(self):
        super().__init__()
        self._recognizer = None

    @property
    def available(self) -> bool:
        try:
            import vosk  # noqa: F401
        except Exception:
            return False
        return self.model_dir().exists()

    @staticmethod
    def model_dir() -> Path:
        return VOSK_DIR / VOSK_MODEL_NAME

    def ensure_model(self, report) -> bool:
        """Download + extract the small French model once (about 40 MB)."""
        if self.model_dir().exists():
            return True
        try:
            import requests
        except ImportError:
            report("pip install requests nécessaire pour télécharger le modèle.")
            return False
        archive = VOSK_DIR / f"{VOSK_MODEL_NAME}.zip"
        VOSK_DIR.mkdir(parents=True, exist_ok=True)
        report(f"téléchargement du modèle vocal local (~40 Mo)…")
        try:
            with requests.get(VOSK_URL, stream=True, timeout=60) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length", 0) or 0)
                done = 0
                with open(archive, "wb") as fh:
                    for chunk in resp.iter_content(chunk_size=1 << 18):
                        fh.write(chunk)
                        done += len(chunk)
                        if total and (done // (2 << 20)) != ((done - len(chunk)) // (2 << 20)):
                            report(f"téléchargement {done >> 20}/{total >> 20} Mo…")
            report("extraction du modèle…")
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(VOSK_DIR)
            archive.unlink(missing_ok=True)
            report("modèle vocal prêt.")
            return self.model_dir().exists()
        except Exception as exc:
            report(f"téléchargement du modèle impossible : {exc}")
            try:
                archive.unlink(missing_ok=True)
            except OSError:
                pass
            return False

    def _setup(self) -> str:
        try:
            from vosk import Model, KaldiRecognizer
            model = Model(str(self.model_dir()))
            self._recognizer = KaldiRecognizer(
                model, RATE, json.dumps(VOSK_KEYWORDS + ["[unk]"]))
        except Exception as exc:
            self._recognizer = None
            return f"initialisation vosk impossible : {exc}"
        return ""

    def _process(self, block: np.ndarray):
        rec = self._recognizer
        if rec is None:
            return
        data = block.tobytes()
        text = ""
        if rec.AcceptWaveform(data):
            text = json.loads(rec.Result()).get("text", "")
        else:
            text = json.loads(rec.PartialResult()).get("partial", "")
        if "niang" in text:
            self._notify(f"détection (« {text} »)")
            rec.Reset()
            self._fire()

    def _teardown(self):
        self._recognizer = None

    def _fire(self):
        if self._on_detect:
            try:
                self._on_detect()
            except Exception as exc:
                self._notify(f"erreur de callback : {exc}")


def find_custom_model() -> str | None:
    for candidate in CUSTOM_MODEL_CANDIDATES:
        if (MODELS_DIR / candidate).exists():
            return candidate
    return None


# ── Orchestrator ─────────────────────────────────────────────────────────────

class VoiceActivation:

    def __init__(self, on_detect=None, log=None):
        self._on_detect = on_detect
        self._log = log or (lambda msg: print(f"[VoiceActivation] {msg}"))
        self._on_state_change = None   # callable(active: bool) -> None
        self._on_level = None          # callable(level 0..1) -> None
        self._engine = None
        self._last_trigger = 0.0
        self._fire_lock = threading.Lock()
        self._levels = deque(maxlen=240)      # ~20 s of mic levels
        self._silent_warned_at = 0.0

    # -- logging -------------------------------------------------------------
    def _report(self, message: str):
        try:
            self._log(message)
        except Exception:
            pass

    def _notify_state(self, active: bool):
        cb = self._on_state_change
        if cb:
            try:
                cb(active)
            except Exception:
                pass

    def _forward_level(self, level: float):
        now = time.monotonic()
        self._levels.append((now, level))
        # Microphone sanity check: a muted / unplugged mic produces silence.
        if self._engine is not None and self._engine.running:
            window = [v for t, v in self._levels if now - t < 15.0]
            if window and max(window) < 0.01 and now - self._silent_warned_at > 60:
                self._silent_warned_at = now
                self._report(
                    "⚠️ le microphone ne capte aucun signal (muet ou "
                    "débranché) — le mot d« activation ne peut pas être détecté.")
        cb = self._on_level
        if cb:
            try:
                cb(level)
            except Exception:
                pass

    # -- engine selection ----------------------------------------------------
    def _build_engine(self):
        model_file = find_custom_model()
        if model_file:
            engine = OwwWakeEngine(model_file)
            if engine.available:
                return engine
        settings = load_settings()
        if settings.get("vosk_enabled", True):
            engine = VoskWakeEngine()
            if engine.available:
                return engine
        return None

    def engine_info(self) -> str:
        if self._engine is not None:
            return (f"actif — moteur {self._engine.name} "
                    f"(modèle : {getattr(self._engine, 'model_file', VOSK_MODEL_NAME)})")
        model_file = find_custom_model()
        if model_file:
            return (f"moteur openwakeword disponible ({model_file}) mais arrêté")
        try:
            import vosk  # noqa: F401
            return ("moteur vosk disponible — modèle local à télécharger "
                    "au premier démarrage")
        except ImportError:
            return ("aucun moteur : pip install vosk (recommandé) ou entraîner "
                    "le modèle 'Hey Niang' avec les commandes vocales "
                    "'record the wake word' puis 'train the wake word'")

    def status(self) -> str:
        running = self._engine.running if self._engine else False
        return f"{'active' if running else 'inactive'} — {self.engine_info()}"

    # -- refractory-wrapped trigger -------------------------------------------
    def _trigger(self):
        now = time.monotonic()
        settings = load_settings()
        refractory = float(settings.get("refractory_seconds", 3.0))
        with self._fire_lock:
            if now - self._last_trigger < refractory:
                self._report("activation ignorée (période de garde)")
                return
            self._last_trigger = now
        if self._on_detect:
            try:
                self._on_detect()
            except Exception as exc:
                self._report(f"erreur de callback : {exc}")

    # -- lifecycle ------------------------------------------------------------
    def auto_start(self) -> str:
        """Start on boot if permanent listening is enabled in the settings."""
        settings = load_settings()
        if not settings.get("wake_word_enabled", True):
            self._report("écoute permanente désactivée dans les paramètres.")
            return "disabled"
        return self.start()

    def start(self) -> str:
        if self._engine is not None and self._engine.running:
            return "already"
        engine = self._build_engine()
        if engine is None:
            message = self.engine_info()
            self._report(message)
            return message
        if isinstance(engine, VoskWakeEngine) and not engine.model_dir().exists():
            engine.ensure_model(self._report)
        result = engine.start(
            on_detect=self._trigger, on_status=self._report,
            on_level=self._forward_level)
        if engine.running:
            self._engine = engine
            self._notify_state(True)
            self._report(result)
        else:
            self._report(result)
        return result

    def stop(self) -> str:
        engine, self._engine = self._engine, None
        if engine is None:
            return "inactive"
        result = engine.stop()
        self._notify_state(False)
        self._report(result)
        return result

    def toggle(self) -> str:
        if self._engine is not None and self._engine.running:
            result = self.stop()
            enabled = False
        else:
            result = self.start()
            enabled = self._engine is not None and self._engine.running
        save_settings({"wake_word_enabled": enabled})
        return result


# Module-level single instance (used by main.py / tray / voice tools)
voice_activation = VoiceActivation()


# ── CLI self-test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("settings:", load_settings())
    print("modèle personnalisé :", find_custom_model() or "aucun")
    print("vosk installé :", end=" ")
    try:
        import vosk  # noqa: F401
        print("oui")
    except ImportError:
        print("non (pip install vosk)")
    print("moteur :", voice_activation.engine_info())
