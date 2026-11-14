"""Tunable configuration for the NIANG IA continuous screen-vision engine.

Every knob that influences CPU usage, latency or privacy lives here so the
engine stays predictable and testable.  Values are deliberately conservative:
the engine must stay usable on a laptop while NIANG IA runs in the tray.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(slots=True)
class VisionConfig:
    """Runtime configuration for :class:`vision_engine.engine.VisionEngine`."""

    # ── Capture cadence ────────────────────────────────────────────────────
    # `idle_interval` is used when nothing changed recently, `active_interval`
    # right after a change.  This is the main CPU lever of the whole engine.
    idle_interval: float = 0.50
    active_interval: float = 0.20
    # The engine backs off up to this interval when the screen stays quiet.
    max_idle_interval: float = 2.00
    signature_size: tuple[int, int] = (160, 90)

    # ── Change detection ───────────────────────────────────────────────────
    # `base_change_threshold` is the minimum mean-pixel delta (0-255) that
    # counts as a change.  The effective threshold adapts upward when the
    # screen is noisy (video playback, animations) so the engine does not spin.
    base_change_threshold: float = 2.5
    adaptive_multiplier: float = 4.0
    max_change_threshold: float = 18.0
    stable_samples: int = 2
    region_grid: tuple[int, int] = (8, 5)
    region_min_score: float = 1.0
    # A change must reach this multiple of the base threshold before it
    # triggers an automatic deep analysis.  Small flickers (a blinking cursor)
    # stay cheap.
    deep_trigger_multiplier: float = 2.0

    # ── Analysis depth ─────────────────────────────────────────────────────
    deep_analysis: bool = True
    # Minimum delay between two automatic deep analyses.  Deep analysis runs
    # OCR and UI Automation, which is expensive; the engine must never let it
    # saturate the CPU.
    deep_min_interval: float = 15.0
    ocr_enabled: bool = True
    ocr_languages: str = "eng"
    ocr_min_confidence: float = 35.0
    # Tesseract page-segmentation mode (11 = sparse text, the fastest).
    ocr_psm: int = 11
    # "foreground" restricts the OCR to the focused window, "full" reads the
    # whole desktop.
    ocr_region: str = "foreground"
    uia_enabled: bool = True
    uia_max_controls: int = 120
    uia_timeout: float = 4.0
    window_poll_interval: float = 1.0
    max_text_chars: int = 4000
    deep_delay_max: float = 4.0

    # ── Privacy ────────────────────────────────────────────────────────────
    privacy_mode: bool = False
    redact_passwords: bool = True

    # ── Memory ─────────────────────────────────────────────────────────────
    memory_retention: int = 50
    max_failures: int = 30
    memory_path: str | None = None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["signature_size"] = list(self.signature_size)
        data["region_grid"] = list(self.region_grid)
        return data

    @classmethod
    def from_dict(cls, data: dict | None) -> "VisionConfig":
        data = dict(data or {})
        for key in ("signature_size", "region_grid"):
            if key in data and data[key] is not None:
                data[key] = tuple(data[key])
        allowed = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in allowed})


# Backwards-compatible alias used by some call sites.
VisionEngineConfig = VisionConfig

DEFAULT_CONFIG = VisionConfig()

__all__ = ["VisionConfig", "VisionEngineConfig", "DEFAULT_CONFIG"]
