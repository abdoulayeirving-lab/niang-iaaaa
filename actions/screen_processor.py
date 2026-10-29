import io
import json
import sys
import time
import cv2
import mss
import mss.tools
from pathlib import Path

# Ensure the project root is importable when this file runs directly.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import PIL.Image
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

from google import genai

def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"

IMG_MAX_W = 640
IMG_MAX_H = 360
JPEG_Q    = 55


def _get_api_key() -> str:
    from api_keys import next_key
    return next_key()


def _get_camera_index() -> int:
    try:
        with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        if "camera_index" in cfg:
            return int(cfg["camera_index"])
    except Exception:
        pass

    print("[Camera] ðŸ” No camera index in config. Auto-detecting...")
    best_index = 0

    for idx in range(6):
        cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap.release()
            continue
        for _ in range(5):
            cap.read()
        ret, frame = cap.read()
        cap.release()
        if ret and frame is not None and frame.mean() > 5:
            best_index = idx
            print(f"[Camera] âœ… Camera found at index {idx} â€” saving to config.")
            break
        else:
            print(f"[Camera] âš ï¸  Index {idx}: no valid frame.")

    try:
        cfg = {}
        if API_CONFIG_PATH.exists():
            with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        cfg["camera_index"] = best_index
        with open(API_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4)
        print(f"[Camera] ðŸ’¾ Camera index {best_index} saved to config.")
    except Exception as e:
        print(f"[Camera] âš ï¸  Could not save camera index: {e}")

    return best_index


def _to_jpeg(img_bytes: bytes) -> bytes:
    if not _PIL_OK:
        return img_bytes
    img = PIL.Image.open(io.BytesIO(img_bytes)).convert("RGB")
    img.thumbnail([IMG_MAX_W, IMG_MAX_H], PIL.Image.BILINEAR)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_Q, optimize=False)
    return buf.getvalue()


def _capture_screenshot() -> bytes:
    with mss.mss() as sct:
        shot      = sct.grab(sct.monitors[1])
        png_bytes = mss.tools.to_png(shot.rgb, shot.size)
    return _to_jpeg(png_bytes)


def _capture_camera() -> bytes:
    camera_index = _get_camera_index()
    cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
    if not cap.isOpened():
        raise RuntimeError(f"Camera could not be opened: index {camera_index}")
    for _ in range(10):
        cap.read()
    ret, frame = cap.read()
    cap.release()
    if not ret or frame is None:
        raise RuntimeError("Could not capture camera frame.")
    if _PIL_OK:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = PIL.Image.fromarray(rgb)
        img.thumbnail([IMG_MAX_W, IMG_MAX_H], PIL.Image.BILINEAR)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=JPEG_Q, optimize=False)
        return buf.getvalue()
    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_Q])
    return buf.tobytes()


def _analyze_image_text(image_bytes: bytes, mime_type: str, user_text: str, model: str = "gemini-3.8-flash") -> str:
    """Synchronous vision: send image + question to Gemini, return the text answer.
    This is the path that feeds vision results BACK into the main conversation."""
    import google.genai.types as gtypes
    client = genai.Client(
        api_key=_get_api_key(),
        http_options={"api_version": "v1beta"}
    )
    prompt = (
        "You are NIANG IA's vision module. Analyze the attached image and answer "
        "the user's question. Be concise, accurate, and address the user as 'sir'. "
        "Max 2-3 short sentences. The main assistant will relay your answer.\n\n"
        f"User's question: {user_text}"
    )
    try:
        resp = None
        last_error = None
        models_to_try = list(dict.fromkeys([
            model,
            "gemini-3.6-flash",
            "gemini-3.5-flash",
        ]))

        for candidate in models_to_try:
            print(f"[ScreenProcess] Essai du modele : {candidate}")
            for attempt in range(2):
                try:
                    resp = client.models.generate_content(
                        model=candidate,
                        contents=[
                            gtypes.Part.from_bytes(
                                data=image_bytes,
                                mime_type=mime_type,
                            ),
                            prompt,
                        ],
                    )
                    break
                except Exception as attempt_error:
                    last_error = attempt_error
                    error_text = str(attempt_error)
                    temporary = (
                        "503" in error_text
                        or "UNAVAILABLE" in error_text
                        or "429" in error_text
                        or "RESOURCE_EXHAUSTED" in error_text
                    )
                    model_missing = (
                        "404" in error_text
                        or "NOT_FOUND" in error_text
                    )

                    if not temporary and not model_missing:
                        raise

                    if temporary and attempt == 0:
                        print(
                            f"[ScreenProcess] {candidate} est temporairement "
                            "indisponible. Nouvelle tentative dans 2s..."
                        )
                        time.sleep(2)
                        continue

                    print(
                        f"[ScreenProcess] Passage au modele de secours "
                        f"apres l'echec de {candidate}."
                    )
                    break

            if resp is not None:
                break

        if resp is None:
            raise RuntimeError(
                f"Aucun modele de vision n'a repondu. Derniere erreur : {last_error}"
            )
        text = (resp.text or "").strip()
        if not text:
            return "I looked at the image but couldn't make out an answer, sir."
        return text
    except Exception as e:
        return f"Vision analysis failed: {e}"


def screen_process(
    parameters:     dict,
    response:       str | None = None,
    player=None,
    session_memory=None,
) -> str:
    user_text = (parameters or {}).get("text") or (parameters or {}).get("user_text", "")
    user_text = (user_text or "").strip()
    if not user_text:
        return "No question provided for screen analysis, sir."

    angle = (parameters or {}).get("angle", "screen").lower().strip()
    if angle != "camera":
        from actions.local_screen_monitor import monitor_status
        status = monitor_status()
        return (
            "Screen-image analysis is disabled: NIANG IA never sends screenshots "
            "to Gemini. Local screen monitor status: "
            f"{status['state']}; changes detected: {status['changes_detected']}."
        )
    print(f"[ScreenProcess] angle={angle!r}  text={user_text!r}")

    try:
        image_bytes = _capture_camera()
        mime_type   = "image/jpeg"
        print("[ScreenProcess] ðŸ“· Camera captured")
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"[ScreenProcess] âŒ Capture error: {e}")
        return f"Screen capture failed: {e}"

    print(f"[ScreenProcess] ðŸ“¦ {len(image_bytes)} bytes â†’ analyzing")
    answer = _analyze_image_text(image_bytes, mime_type, user_text)
    if player:
        player.write_log(f"NIANG IA: {answer}")
    print(f"[ScreenProcess] ðŸ’¬ {answer}")
    return answer


if __name__ == "__main__":
    print("[TEST] screen_processor.py v9 â€” image-only analysis")
    print("=" * 50)
    mode    = input("screen / camera (default: screen): ").strip().lower() or "screen"
    request = input("Question (Enter for default): ").strip() or "What do you see? Be brief."

    t0     = time.perf_counter()
    result = screen_process({"angle": mode, "text": request}, player=None)
    print(f"Analyzed â€” {time.perf_counter()-t0:.3f}s")
    print(f"\n{'âœ…' if result else 'âŒ'}")


