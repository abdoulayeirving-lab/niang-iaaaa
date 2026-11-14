"""Optional multimodal provider for high-quality captioning and VQA."""

from __future__ import annotations

import io
from typing import Any


class MultimodalVision:
    """Use the configured Gemini API only when explicitly available."""

    def __init__(self, model: str = "gemini-2.5-flash"):
        self.model = model
        self._client = None
        self.error: str | None = None

    def _load(self) -> bool:
        if self._client is not None:
            return True
        try:
            from google import genai
            from api_keys import next_key
            self._client = genai.Client(api_key=next_key())
            return True
        except Exception as exc:
            self.error = f"Multimodal provider unavailable: {exc}"
            return False

    def ask(self, frame: Any, question: str = "Describe this image in detail.") -> str:
        """Return the model answer, or an explicit error string (never confuse them)."""
        if frame is None or not self._load():
            return f"Multimodal provider unavailable: {self.error or 'unknown error'}"
        try:
            import cv2
            from google.genai import types
            ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
            if not ok:
                return "Could not encode the camera frame."
            response = self._client.models.generate_content(
                model=self.model,
                contents=[types.Part.from_bytes(data=encoded.tobytes(), mime_type="image/jpeg"), question],
            )
            answer = (response.text or "").strip()
            self.error = None
            if not answer:
                return "The multimodal model returned an empty answer."
            return answer
        except Exception as exc:
            self.error = f"Multimodal inference failed: {exc}"
            # Distinguish an error from a model answer: the error is returned as
            # an error string, never as if it were the model's response.
            return f"Multimodal inference failed: {exc}"
