"""Multi-key Gemini API rotation.

Reads all configured API keys (legacy `gemini_api_key` + new list
`gemini_api_keys`) from config/api_keys.json and the optional installer key
file. When a key hits the free-tier
daily quota (429 RESOURCE_EXHAUSTED), it is marked exhausted with a cooldown
and the next configured key is tried automatically. Keys recover once the
cooldown expires (daily quota resets), so old keys keep working again later.
"""
import hashlib
import json
import os
import sys
import threading
import time
from pathlib import Path


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


CONFIG_PATH = get_base_dir() / "config" / "api_keys.json"
INSTALLER_KEY_PATH = get_base_dir() / "config" / "installer_gemini_key.txt"
_LOCAL_DATA_DIR = Path(
    os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
)
SECURE_KEYS_PATH = _LOCAL_DATA_DIR / "NIANG IA" / "api_keys.dpapi"
STATE_PATH  = get_base_dir() / "config" / "api_key_state.json"
DOTENV_PATH = get_base_dir() / ".env"

_ENV_FILE_KEYS = {
    "SERPER_API_KEY",
    "KAIZUMI_GEMINI_API_KEY",
    "KAIZUMI_GEMINI_API_KEYS",
}

# Free-tier daily quota resets ~midnight; 8h cooldown is a safe approximation.
RESET_COOLDOWN = 8 * 3600

_lock  = threading.Lock()
_state = None  # {key_hash: {"until": ts}}
_pos   = 0


def _hash(key: str) -> str:
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def load_env_file() -> None:
    """Load supported local API settings without overriding process variables."""
    try:
        lines = DOTENV_PATH.read_text(encoding="utf-8-sig").splitlines()
    except FileNotFoundError:
        return

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        name = name.strip()
        if name not in _ENV_FILE_KEYS:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(name, value)


def _load_state() -> dict:
    global _state
    if _state is None:
        try:
            _state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            _state = {}
    return _state


def _save_state() -> None:
    try:
        tmp = STATE_PATH.with_suffix(STATE_PATH.suffix + ".tmp")
        tmp.write_text(json.dumps(_state, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, STATE_PATH)
    except Exception:
        pass


def _read_secure_keys() -> list[str]:
    try:
        encrypted = SECURE_KEYS_PATH.read_bytes()
    except FileNotFoundError:
        return []
    if sys.platform != "win32":
        raise RuntimeError("Protected API key storage requires Windows DPAPI.")
    import win32crypt

    decrypted = win32crypt.CryptUnprotectData(
        encrypted, None, None, None, 0
    )[1]
    if isinstance(decrypted, bytes):
        decrypted = decrypted.decode("utf-8")
    values = json.loads(decrypted)
    if not isinstance(values, list) or not all(
        isinstance(value, str) for value in values
    ):
        raise ValueError("Protected API key storage has an invalid format.")
    return [value.strip() for value in values if value.strip()]


def _write_secure_keys(keys: list[str]) -> None:
    if sys.platform != "win32":
        raise RuntimeError("Protected API key storage requires Windows DPAPI.")
    import win32crypt

    encrypted = win32crypt.CryptProtectData(
        json.dumps(keys, ensure_ascii=False).encode("utf-8"),
        "NIANG IA API keys",
        None,
        None,
        None,
        0,
    )
    SECURE_KEYS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = SECURE_KEYS_PATH.with_suffix(".tmp")
    try:
        temporary_path.write_bytes(encrypted)
        os.replace(temporary_path, SECURE_KEYS_PATH)
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def get_all_keys() -> list:
    load_env_file()
    keys = []
    # Environment variables first (dev / CI / docker friendly).
    env_key = os.environ.get("KAIZUMI_GEMINI_API_KEY", "").strip()
    env_keys = os.environ.get("KAIZUMI_GEMINI_API_KEYS", "").strip()
    if env_key:
        keys.append(env_key)
    if env_keys:
        keys.extend(k.strip() for k in env_keys.split(",") if k.strip())
    try:
        installer_key = INSTALLER_KEY_PATH.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        installer_key = ""
    if installer_key:
        keys.append(installer_key)
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        cfg = {}
    single = cfg.get("gemini_api_key")
    if isinstance(single, str) and single.strip():
        keys.append(single.strip())
    lst = cfg.get("gemini_api_keys")
    if isinstance(lst, list):
        keys.extend(k.strip() for k in lst if isinstance(k, str) and k.strip())
    keys.extend(_read_secure_keys())
    seen, out = set(), []
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def mark_exhausted(key: str) -> None:
    if not key:
        return
    with _lock:
        st = _load_state()
        st[_hash(key)] = {"until": time.time() + RESET_COOLDOWN}
        _save_state()


def next_key() -> str:
    """Return the next available key, preferring ones not in cooldown."""
    global _pos
    with _lock:
        keys = get_all_keys()
        if not keys:
            raise KeyError("gemini_api_key not configured in config/api_keys.json")
        st = _load_state()
        now = time.time()
        n   = len(keys)
        pos = _pos % n
        for i in range(n):
            k = keys[(pos + i) % n]
            entry = st.get(_hash(k))
            if not entry or entry.get("until", 0) <= now:
                _pos = (pos + i + 1) % n
                return k
        # All keys in cooldown — force a retry on the next one (may have recovered).
        k = keys[pos]
        _pos = (pos + 1) % n
        st.pop(_hash(k), None)
        _save_state()
        return k


def _is_quota_error(e) -> bool:
    msg = str(e)
    return ("429" in msg) or ("RESOURCE_EXHAUSTED" in msg)


def add_key(key: str) -> int:
    key = (key or "").strip()
    if not key:
        raise ValueError("Empty API key.")
    with _lock:
        secure_keys = _read_secure_keys()
        if key not in secure_keys:
            secure_keys.append(key)
            _write_secure_keys(secure_keys)
        return len(get_all_keys())


async def aio_generate(model, contents, config=None, api_version=None):
    """Generate content, automatically retrying across all keys on 429."""
    from google import genai

    keys = get_all_keys()
    last_err = None
    for k in keys:
        try:
            kwargs = {}
            if api_version:
                kwargs["http_options"] = {"api_version": api_version}
            client = genai.Client(api_key=k, **kwargs)
            resp = await client.aio.models.generate_content(
                model=model, contents=contents, config=config)
            return resp
        except Exception as e:
            if _is_quota_error(e):
                mark_exhausted(k)
                last_err = e
                continue
            raise
    if last_err is None:
        raise KeyError("No Gemini API keys configured — add one in config/api_keys.json")
    raise last_err


def generate_with_retry(
    model,
    contents,
    config=None,
    api_version=None,
    timeout_ms=None,
):
    """Sync version of aio_generate (for transcribe_voice and legacy modules)."""
    from google import genai

    keys = get_all_keys()
    last_err = None
    deadline = (
        time.monotonic() + timeout_ms / 1000
        if timeout_ms is not None
        else None
    )
    for k in keys:
        try:
            kwargs = {}
            http_options = {}
            if api_version:
                http_options["api_version"] = api_version
            if deadline is not None:
                remaining_ms = int((deadline - time.monotonic()) * 1000)
                if remaining_ms <= 0:
                    raise TimeoutError("Gemini request exceeded its configured timeout.")
                http_options["timeout"] = remaining_ms
            if http_options:
                kwargs["http_options"] = http_options
            client = genai.Client(api_key=k, **kwargs)
            resp = client.models.generate_content(
                model=model, contents=contents, config=config)
            return resp
        except Exception as e:
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError(
                    "Gemini request exceeded its configured timeout."
                ) from e
            if _is_quota_error(e):
                mark_exhausted(k)
                last_err = e
                continue
            raise
    if last_err is None:
        raise KeyError("No Gemini API keys configured — add one in config/api_keys.json")
    raise last_err


class GeminiModel:
    """Small synchronous adapter for the currently supported google-genai SDK."""

    def __init__(
        self,
        model_name: str | None = None,
        *,
        system_instruction: str | None = None,
        generation_config: dict | None = None,
        timeout_s: int | None = None,
    ):
        if not model_name:
            raise ValueError("A Gemini model name is required.")
        self.model_name = model_name
        self.system_instruction = system_instruction
        self.generation_config = generation_config or {}
        if timeout_s is None:
            from agent.settings import gemini_timeout_seconds
            timeout_s = gemini_timeout_seconds()
        if not 1 <= timeout_s <= 1800:
            raise ValueError("Gemini timeout must be between 1 and 1800 seconds.")
        self.timeout_ms = timeout_s * 1000

    def generate_content(self, contents, **kwargs):
        from google.genai import types

        config_values = dict(self.generation_config)
        config_values.update(kwargs)
        if self.system_instruction is not None:
            config_values["system_instruction"] = self.system_instruction
        config = (
            types.GenerateContentConfig(**config_values)
            if config_values
            else None
        )
        return generate_with_retry(
            self.model_name,
            contents,
            config=config,
            timeout_ms=self.timeout_ms,
        )
