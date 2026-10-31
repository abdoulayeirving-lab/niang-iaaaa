import numpy as np
from types import SimpleNamespace
from unittest.mock import patch

from vision.ocr_engine import (
    CodeReader,
    OCREngine,
    OCRConfig,
    _configure_tesseract_path,
)


def test_ocr_without_native_tesseract_is_safe():
    engine = OCREngine(OCRConfig(languages="eng"))
    result = engine.extract(np.zeros((40, 80, 3), dtype=np.uint8))
    assert result == []
    assert engine.error is not None or engine.is_ready


def test_code_reader_handles_empty_frame():
    reader = CodeReader()
    assert reader.read(None) == []


def test_configure_tesseract_path_uses_standard_install_candidates(tmp_path):
    executable = tmp_path / "Tesseract-OCR" / "tesseract.exe"
    executable.parent.mkdir()
    executable.touch()
    module = SimpleNamespace(
        pytesseract=SimpleNamespace(tesseract_cmd="tesseract")
    )

    with (
        patch("vision.ocr_engine.shutil.which", return_value=None),
        patch("vision.ocr_engine._tesseract_candidates", return_value=(executable,)),
    ):
        _configure_tesseract_path(module)

    assert module.pytesseract.tesseract_cmd == str(executable)
