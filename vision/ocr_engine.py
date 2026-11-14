"""Optional OCR adapter with OpenCV preprocessing."""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from time import time
from typing import Any

from .vision_events import VisionEvent


@dataclass(slots=True)
class OCRConfig:
    languages: str = "eng"
    min_confidence: float = 35.0
    scale: float = 1.5
    # Tesseract page-segmentation mode. 3 = full automatic layout analysis
    # (accurate but slow). 6 = a single uniform block, 11 = sparse text.
    # Sparse text is much faster on a busy desktop screen.
    psm: int = 3
    # Downscale the frame so its width never exceeds this many pixels.
    # 0 disables the clamp.
    max_width: int = 0


def _tesseract_candidates() -> tuple[Path, ...]:
    project_root = Path(__file__).resolve().parents[1]
    return (
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "Tesseract-OCR"
        / "tesseract.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "Tesseract-OCR"
        / "tesseract.exe",
        project_root / "runtime" / "Tesseract-OCR" / "tesseract.exe",
        Path(sys.executable).resolve().parent
        / "runtime"
        / "Tesseract-OCR"
        / "tesseract.exe",
    )


def _configure_tesseract_path(pytesseract_module: Any) -> None:
    configured_path = str(pytesseract_module.pytesseract.tesseract_cmd)
    if Path(configured_path).is_file() or shutil.which(configured_path):
        return

    for candidate in _tesseract_candidates():
        if candidate.is_file():
            pytesseract_module.pytesseract.tesseract_cmd = str(candidate)
            return


class OCREngine:
    """Extract text when the optional pytesseract/Tesseract stack is ready."""

    def __init__(self, config: OCRConfig | None = None):
        self.config = config or OCRConfig()
        self._loaded = False
        self._pytesseract = None
        self._error: str | None = None

    @property
    def is_ready(self) -> bool:
        return self._pytesseract is not None and self._error is None

    @property
    def error(self) -> str | None:
        return self._error

    def load(self) -> bool:
        if self._loaded:
            return self.is_ready
        try:
            import pytesseract
            _configure_tesseract_path(pytesseract)
            self._pytesseract = pytesseract
            # This also checks that the native Tesseract executable is present.
            pytesseract.get_tesseract_version()
        except Exception as exc:
            # Stay unloaded so a later call can retry: the native binary may
            # simply not be installed yet.
            self._pytesseract = None
            self._error = f"OCR unavailable: {exc}"
            return False
        self._loaded = True
        self._error = None
        return True

    def extract(self, frame: Any) -> list[VisionEvent]:
        if frame is None or not self.load():
            return []
        try:
            import cv2
            image = frame
            if self.config.scale != 1.0:
                image = cv2.resize(image, None, fx=self.config.scale, fy=self.config.scale,
                                   interpolation=cv2.INTER_CUBIC)
            max_width = int(self.config.max_width or 0)
            if max_width > 0 and image.shape[1] > max_width:
                ratio = max_width / float(image.shape[1])
                image = cv2.resize(
                    image,
                    (max_width, max(1, int(image.shape[0] * ratio))),
                    interpolation=cv2.INTER_AREA,
                )
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (3, 3), 0)
            processed = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
            tesseract_config = f"--psm {int(self.config.psm)}" if self.config.psm else ""
            data = self._pytesseract.image_to_data(
                processed, lang=self.config.languages,
                output_type=self._pytesseract.Output.DICT,
                config=tesseract_config,
            )
            events: list[VisionEvent] = []
            for i, raw_text in enumerate(data.get("text", [])):
                text = str(raw_text).strip()
                try:
                    confidence = float(data["conf"][i])
                except (ValueError, TypeError, KeyError):
                    confidence = 0.0
                if not text or confidence < self.config.min_confidence:
                    continue
                x, y = int(data["left"][i]), int(data["top"][i])
                w, h = int(data["width"][i]), int(data["height"][i])
                events.append(VisionEvent(
                    type="text_detected", timestamp=time(), label=text,
                    confidence=confidence / 100.0, bbox=(x, y, w, h),
                    metadata={"language": self.config.languages},
                ))
            # A successful run clears any previous transient failure.
            self._error = None
            return events
        except Exception as exc:
            self._error = f"OCR inference failed: {exc}"
            return []


class CodeReader:
    """Read QR codes and OpenCV barcode detections from a frame."""

    def __init__(self):
        self._qr = None
        self._barcode = None

    def read(self, frame: Any) -> list[VisionEvent]:
        if frame is None:
            return []
        try:
            import cv2
            if self._qr is None:
                self._qr = cv2.QRCodeDetector()
            events: list[VisionEvent] = []
            data, points, _ = self._qr.detectAndDecode(frame)
            if data:
                bbox = self._points_bbox(points)
                events.append(VisionEvent(
                    type="qr_detected", timestamp=time(), label=data[:500],
                    confidence=1.0, bbox=bbox,
                ))

            barcode_cls = getattr(cv2, "barcode_BarcodeDetector", None)
            if barcode_cls is not None:
                if self._barcode is None:
                    self._barcode = barcode_cls()
                ok, decoded, types, points = self._barcode.detectAndDecode(frame)
                if ok and decoded:
                    for value, code_type in zip(decoded, types or []):
                        if value:
                            events.append(VisionEvent(
                                type="barcode_detected", timestamp=time(), label=str(value),
                                confidence=1.0,
                                metadata={"format": str(code_type)},
                            ))
            return events
        except Exception:
            return []

    @staticmethod
    def _points_bbox(points):
        if points is None:
            return None
        values = points.reshape(-1, 2)
        x0, y0 = values.min(axis=0)
        x1, y1 = values.max(axis=0)
        return int(x0), int(y0), int(x1 - x0), int(y1 - y0)
