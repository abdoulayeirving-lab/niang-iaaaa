"""NIANG IA — continuous screen vision engine.

This package gives NIANG IA a permanent, low-cost perception of the Windows
desktop:

* background capture and visual change detection,
* window and application identification,
* local OCR and UI Automation element discovery,
* a structured representation of the screen,
* contextual visual memory (what changed, what already failed),
* an observe → decide → verify decision loop.

Everything runs locally: no screenshot and no OCR text is sent to a remote
service by this package.

Typical use::

    from vision_engine import VisionEngine

    engine = VisionEngine()
    engine.start()
    observation = engine.observe_now(deep=True)
    print(observation.summary())
    engine.stop()
"""

from __future__ import annotations

from .capture import CaptureFrame, MonitorInfo, ScreenCapture
from .change import ChangeDetector, ChangeResult
from .config import DEFAULT_CONFIG, VisionConfig, VisionEngineConfig
from .decision import (
    DECISION_ABORT,
    DECISION_CONFIRM,
    DECISION_PROCEED,
    Decision,
    DecisionEngine,
    VerificationResult,
)
from .elements import InteractiveElement, UIAInspector
from .engine import (
    STATE_DEGRADED,
    STATE_EMERGENCY,
    STATE_ERROR,
    STATE_PRIVACY,
    STATE_RUNNING,
    STATE_STARTING,
    STATE_STOPPED,
    VisionEngine,
)
from .events import VisionEvent, VisionEventBus
from .memory import VisualMemory
from .ocr import ScreenOCR, TextBlock
from .privacy import REDACTED, PrivacyGuard
from .scene import ScreenObservation, detect_problems
from .windows import WindowInfo, WindowTracker

__all__ = [
    "VisionEngine",
    "VisionConfig",
    "VisionEngineConfig",
    "DEFAULT_CONFIG",
    "VisionEvent",
    "VisionEventBus",
    "ScreenCapture",
    "CaptureFrame",
    "MonitorInfo",
    "ChangeDetector",
    "ChangeResult",
    "WindowTracker",
    "WindowInfo",
    "UIAInspector",
    "InteractiveElement",
    "ScreenOCR",
    "TextBlock",
    "PrivacyGuard",
    "REDACTED",
    "ScreenObservation",
    "detect_problems",
    "VisualMemory",
    "DecisionEngine",
    "Decision",
    "VerificationResult",
    "DECISION_PROCEED",
    "DECISION_CONFIRM",
    "DECISION_ABORT",
    "STATE_STOPPED",
    "STATE_STARTING",
    "STATE_RUNNING",
    "STATE_DEGRADED",
    "STATE_ERROR",
    "STATE_PRIVACY",
    "STATE_EMERGENCY",
]

__version__ = "1.0.0"
