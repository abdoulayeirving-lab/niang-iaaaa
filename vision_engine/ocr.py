"""Local OCR wrapper for the vision engine.

The engine reuses `vision.ocr_engine.OCREngine` (Tesseract) but hardens it:

* a failed load is retried instead of latched forever,
* a transient extraction failure does not poison the engine permanently,
* OCR text is returned as structured blocks with absolute screen coordinates.

OCR is local only: no image and no text ever leaves the machine through this
module.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class TextBlock:
    """One OCR word with its position on the virtual desktop."""

    text: str
    confidence: float = 0.0
    left: int = 0
    top: int = 0
    width: int = 0
    height: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "confidence": round(float(self.confidence), 3),
            "bounds": {
                "left": self.left,
                "top": self.top,
                "width": self.width,
                "height": self.height,
            },
        }


def _crop(
    frame: Any, region: tuple[int, int, int, int] | None
) -> tuple[Any, int, int, int]:
    """Crop ``frame`` to ``region``.

    Returns ``(crop, offset_x, offset_y, scale)``.  ``scale`` is the factor
    that must be applied to coordinates coming back from the OCR engine so
    they refer to the original frame.
    """
    if not region:
        return frame, 0, 0, 1
    try:
        left, top, width, height = (int(value) for value in region)
    except (TypeError, ValueError):
        return frame, 0, 0, 1
    if width <= 0 or height <= 0:
        return None, 0, 0, 1
    try:
        frame_height, frame_width = frame.shape[:2]
    except Exception:
        return frame, 0, 0, 1
    left = max(0, min(left, frame_width - 1))
    top = max(0, min(top, frame_height - 1))
    width = max(1, min(width, frame_width - left))
    height = max(1, min(height, frame_height - top))
    return frame[top : top + height, left : left + width], left, top, 1


class ScreenOCR:
    """Thread-safe façade over the local Tesseract OCR engine."""

    def __init__(
        self,
        languages: str = "eng",
        min_confidence: float = 35.0,
        *,
        scale: float = 1.0,
        psm: int = 11,
        retry_cooldown: float = 20.0,
    ) -> None:
        self.languages = languages
        self.min_confidence = float(min_confidence)
        self.scale = float(scale)
        self.psm = int(psm)
        self.retry_cooldown = float(retry_cooldown)
        self._lock = threading.RLock()
        self._engine: Any = None
        self._error: str | None = None
        self._retry_at = 0.0
        self._reads = 0

    # ── State ───────────────────────────────────────────────────────────────
    @property
    def error(self) -> str | None:
        return self._error

    @property
    def reads(self) -> int:
        return self._reads

    def available(self) -> bool:
        """True when the OCR backend can be used right now."""
        with self._lock:
            if self._engine is not None:
                return True
            if time.monotonic() < self._retry_at:
                return False
            return self._ensure_engine() is not None

    def reset(self) -> None:
        """Force a reload of the backend on the next call."""
        with self._lock:
            self._engine = None
            self._retry_at = 0.0

    # ── Reading ────────────────────────────────────────────────────────────
    def read(
        self,
        frame: Any,
        origin: tuple[int, int] = (0, 0),
        region: tuple[int, int, int, int] | None = None,
    ) -> list[TextBlock]:
        """OCR ``frame`` (BGR ndarray) and return positioned text blocks.

        ``region`` restricts the OCR to a sub-rectangle of the frame given as
        ``(left, top, width, height)`` in frame coordinates.  Cropping keeps
        the original resolution — which Tesseract needs to read small text —
        and makes the operation far faster than OCR-ing a whole desktop.

        The returned blocks always use absolute screen coordinates.
        """
        if frame is None:
            return []
        crop, offset_x, offset_y, scale = _crop(frame, region)
        if crop is None:
            return []
        with self._lock:
            engine = self._ensure_engine()
            if engine is None:
                return []
            try:
                events = engine.extract(crop)
            except Exception as exc:
                self._error = f"Local OCR failed: {exc}"
                self._engine = None
                self._retry_at = time.monotonic() + self.retry_cooldown
                return []
            if engine.error:
                # The underlying engine latches its error: rebuild it next time.
                self._error = str(engine.error)
                self._engine = None
                self._retry_at = time.monotonic() + self.retry_cooldown
                return []
            self._error = None
            self._reads += 1
            base_x, base_y = int(origin[0]), int(origin[1])
            blocks: list[TextBlock] = []
            for event in events:
                label = str(getattr(event, "label", "") or "").strip()
                bbox = getattr(event, "bbox", None)
                if not label or not bbox:
                    continue
                blocks.append(
                    TextBlock(
                        text=label,
                        confidence=float(getattr(event, "confidence", 0.0) or 0.0),
                        left=base_x + offset_x + int(bbox[0]) * scale,
                        top=base_y + offset_y + int(bbox[1]) * scale,
                        width=int(bbox[2]) * scale,
                        height=int(bbox[3]) * scale,
                    )
                )
            return blocks

    def read_text(
        self,
        frame: Any,
        origin: tuple[int, int] = (0, 0),
        region: tuple[int, int, int, int] | None = None,
    ) -> str:
        """Read the frame and return the text grouped into readable lines."""
        blocks = self.read(frame, origin, region)
        if not blocks:
            return ""
        return join_lines(blocks)

    # ── Internals ───────────────────────────────────────────────────────────
    def _ensure_engine(self) -> Any:
        if self._engine is not None:
            return self._engine
        if time.monotonic() < self._retry_at:
            return None
        try:
            from vision.ocr_engine import OCRConfig, OCREngine
        except Exception as exc:
            self._error = f"OCR backend is unavailable: {exc}"
            self._retry_at = time.monotonic() + self.retry_cooldown
            return None
        try:
            engine = OCREngine(
                OCRConfig(
                    languages=self.languages,
                    min_confidence=self.min_confidence,
                    scale=self.scale,
                    psm=self.psm,
                )
            )
            if not engine.load():
                self._error = engine.error or "Local OCR is unavailable."
                self._retry_at = time.monotonic() + self.retry_cooldown
                return None
        except Exception as exc:
            self._error = f"OCR backend failed to start: {exc}"
            self._retry_at = time.monotonic() + self.retry_cooldown
            return None
        self._engine = engine
        self._error = None
        return self._engine


def join_lines(blocks: list[TextBlock]) -> str:
    """Group positioned OCR words into lines, top to bottom."""
    if not blocks:
        return ""
    rows: list[dict[str, Any]] = []
    for block in sorted(
        blocks, key=lambda item: (item.top + item.height / 2, item.left)
    ):
        center = block.top + block.height / 2
        row = next(
            (
                candidate
                for candidate in rows
                if abs(center - candidate["center"]) <= max(8, block.height * 0.6)
            ),
            None,
        )
        if row is None:
            rows.append({"center": center, "words": [(block.left, block.text)]})
        else:
            row["words"].append((block.left, block.text))
            row["center"] = (row["center"] + center) / 2
    lines: list[str] = []
    for row in sorted(rows, key=lambda item: item["center"]):
        words = [text for _x, text in sorted(row["words"])]
        line = " ".join(words).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


__all__ = ["ScreenOCR", "TextBlock", "join_lines"]
