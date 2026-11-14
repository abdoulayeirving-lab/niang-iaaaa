"""NIANG IA continuous screen-vision engine.

Design goals (in order):

1. **Stability** — the engine must never crash the host application.
2. **Reliable vision** — a clean, structured picture of what is on screen.
3. **Low resource usage** — nothing is captured or analysed needlessly.
4. **Safety** — screenshots never hit the disk, secrets are redacted.

Execution model
---------------

Two daemon threads:

* **the fast loop** grabs a tiny grayscale signature, detects changes and polls
  the window list.  It never runs OCR or UI Automation, so it stays cheap and
  responsive.
* **the deep worker** performs the expensive analysis (full frame + OCR +
  UI Automation) only when the screen actually changed and settled down, or
  when somebody explicitly asks for a deep observation.

So the resting cost is one small screen grab every ``idle_interval`` seconds.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from .capture import ScreenCapture
from .change import ChangeDetector
from .config import VisionConfig
from .elements import UIAInspector
from .events import (
    EVENT_CAPTURE_LOST,
    EVENT_CAPTURE_RESTORED,
    EVENT_EMERGENCY_STOP,
    EVENT_ENGINE_ERROR,
    EVENT_ENGINE_STARTED,
    EVENT_ENGINE_STOPPED,
    EVENT_OBSERVATION,
    EVENT_PRIVACY_MODE,
    EVENT_PROBLEM_DETECTED,
    EVENT_SCREEN_CHANGED,
    EVENT_WINDOW_CLOSED,
    EVENT_WINDOW_FOCUSED,
    EVENT_WINDOW_OPENED,
    VisionEventBus,
)
from .memory import VisualMemory
from .ocr import ScreenOCR
from .privacy import PrivacyGuard
from .scene import ScreenObservation, detect_problems
from .windows import WindowInfo, WindowTracker

STATE_STOPPED = "stopped"
STATE_STARTING = "starting"
STATE_RUNNING = "running"
STATE_DEGRADED = "degraded"
STATE_ERROR = "error"
STATE_PRIVACY = "privacy"
STATE_EMERGENCY = "emergency_stopped"


class VisionEngine:
    """Continuous, non-blocking screen observation."""

    def __init__(
        self,
        config: VisionConfig | None = None,
        *,
        memory: VisualMemory | None = None,
        bus: VisionEventBus | None = None,
        capture: ScreenCapture | None = None,
        tracker: WindowTracker | None = None,
        inspector: UIAInspector | None = None,
        ocr: ScreenOCR | None = None,
        privacy: PrivacyGuard | None = None,
    ) -> None:
        self._config = config or VisionConfig()
        self._memory = memory or VisualMemory(self._config)
        self._bus = bus or VisionEventBus()
        self._capture = capture or ScreenCapture(self._config)
        self._tracker = tracker or WindowTracker()
        self._inspector = inspector or UIAInspector(
            max_controls=self._config.uia_max_controls,
            timeout=self._config.uia_timeout,
        )
        self._ocr = ocr or ScreenOCR(
            languages=self._config.ocr_languages,
            min_confidence=self._config.ocr_min_confidence,
            psm=self._config.ocr_psm,
        )
        self._privacy = privacy or PrivacyGuard(
            enabled=self._config.privacy_mode,
            redact_passwords=self._config.redact_passwords,
        )

        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._deep_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._deep_thread: threading.Thread | None = None
        self._state = STATE_STOPPED
        self._error: str | None = None
        self._emergency = False
        # OCR reads the text displayed on the screen: it stays disabled until
        # the user explicitly allows screen-text reading.
        self._ocr_permitted = False

        self._detector = ChangeDetector(self._config)
        self._last_observation: ScreenObservation | None = None
        self._last_windows: list[WindowInfo] = []
        self._last_window_poll = 0.0
        self._change_pending = False
        self._stable_run = 0
        self._change_since = 0.0
        self._capture_failures = 0
        self._captures = 0
        self._analyses = 0
        self._changes = 0
        self._idle_streak = 0
        self._last_deep_at = 0.0
        self._started_at: float | None = None
        self._last_capture_at: float | None = None
        self._last_observation_at: float | None = None

    # ── Public API ──────────────────────────────────────────────────────────
    @property
    def config(self) -> VisionConfig:
        return self._config

    @property
    def memory(self) -> VisualMemory:
        return self._memory

    @property
    def bus(self) -> VisionEventBus:
        return self._bus

    @property
    def privacy(self) -> PrivacyGuard:
        return self._privacy

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._state in {STATE_RUNNING, STATE_STARTING, STATE_DEGRADED}

    @property
    def last_observation(self) -> ScreenObservation | None:
        with self._lock:
            return self._last_observation

    def subscribe(self, callback: Callable[[Any], None]) -> int:
        return self._bus.subscribe(callback)

    def unsubscribe(self, token: int) -> None:
        self._bus.unsubscribe(token)

    # ── Lifecycle ───────────────────────────────────────────────────────────
    def start(self) -> dict[str, Any]:
        """Start the monitoring loops.  Idempotent."""
        with self._lock:
            if self._emergency:
                return {
                    **self.status(),
                    "error": "The vision engine was stopped by the emergency stop.",
                }
            if self._thread is not None and self._thread.is_alive():
                return self.status()
            self._stop_event.clear()
            self._deep_event.clear()
            self._emergency = False
            self._error = None
            self._state = STATE_STARTING
            self._started_at = time.time()
            self._detector.reset()
            self._thread = threading.Thread(
                target=self._run_fast_loop, name="NIANG-VisionEngine", daemon=True
            )
            self._deep_thread = threading.Thread(
                target=self._run_deep_loop, name="NIANG-VisionDeep", daemon=True
            )
            self._thread.start()
            self._deep_thread.start()
        self._bus.emit(EVENT_ENGINE_STARTED, {"config": self._config.to_dict()})
        return self.status()

    def stop(self, timeout: float = 3.0) -> dict[str, Any]:
        """Stop the monitoring loops and release the capture backend."""
        self._stop_event.set()
        self._deep_event.set()
        thread = self._thread
        deep_thread = self._deep_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout)
        if deep_thread is not None and deep_thread is not threading.current_thread():
            deep_thread.join(timeout=timeout)
        with self._lock:
            self._thread = None
            self._deep_thread = None
            self._state = STATE_STOPPED
            self._last_observation = None
        self._capture.close()
        self._bus.emit(EVENT_ENGINE_STOPPED, {})
        return self.status()

    def restart(self) -> dict[str, Any]:
        """Stop then start again — used after a fatal capture failure."""
        self.stop()
        with self._lock:
            self._emergency = False
        return self.start()

    def emergency_stop(self) -> dict[str, Any]:
        """Hard stop: no capture, no analysis, no retained observation."""
        with self._lock:
            self._emergency = True
        self._stop_event.set()
        self._deep_event.set()
        thread = self._thread
        deep_thread = self._deep_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        if deep_thread is not None and deep_thread is not threading.current_thread():
            deep_thread.join(timeout=2.0)
        with self._lock:
            self._thread = None
            self._deep_thread = None
            self._state = STATE_EMERGENCY
            self._last_observation = None
            self._change_pending = False
            self._stable_run = 0
            self._ocr_permitted = False
        self._capture.close()
        self._detector.reset()
        self._privacy.set_enabled(True)
        self._bus.emit(EVENT_EMERGENCY_STOP, {"reason": "user requested emergency stop"})
        return self.status()

    def set_privacy_mode(self, enabled: bool) -> dict[str, Any]:
        """Enable or disable privacy mode (no capture at all when enabled)."""
        enabled = bool(enabled)
        self._privacy.set_enabled(enabled)
        with self._lock:
            self._config.privacy_mode = enabled
            if enabled:
                self._state = STATE_PRIVACY if self._thread is not None else STATE_PRIVACY
                self._last_observation = None
            elif self._thread is not None and self._state == STATE_PRIVACY:
                self._state = STATE_RUNNING
        self._detector.reset()
        self._bus.emit(EVENT_PRIVACY_MODE, {"enabled": enabled})
        return self.status()

    def set_ocr_permitted(self, permitted: bool) -> dict[str, Any]:
        """Allow or forbid reading the text displayed on the screen.

        OCR is forbidden by default: it must be enabled explicitly, exactly
        like the screen-OCR consent used by the rest of NIANG IA.
        """
        with self._lock:
            self._ocr_permitted = bool(permitted)
        return self.status()

    @property
    def ocr_permitted(self) -> bool:
        return self._ocr_permitted

    # ── Observation ─────────────────────────────────────────────────────────
    def observe_now(self, *, deep: bool = False, timeout: float = 12.0) -> ScreenObservation:
        """Return a fresh observation.

        ``deep=True`` performs the full analysis (OCR + UI Automation) right
        now; otherwise the last known state is refreshed cheaply.
        """
        if self._privacy.enabled:
            observation = ScreenObservation(
                state=STATE_PRIVACY,
                privacy_mode=True,
                note="Privacy mode is active: the screen is not being observed.",
            )
            with self._lock:
                self._last_observation = observation
            return observation

        if deep:
            observation = self._perform_deep_analysis(
                reason="requested",
                timeout=timeout,
            )
            return observation

        windows = self._safe_window_snapshot()
        observation = self._build_observation(
            windows=windows,
            frame=None,
            deep=False,
            change_score=self._detector.last_score,
            changed=False,
        )
        with self._lock:
            self._last_observation = observation
        return observation

    def observe_window(self, hwnd: int, *, timeout: float = 8.0) -> ScreenObservation:
        """Deep observation restricted to one window."""
        if self._privacy.enabled:
            return ScreenObservation(state=STATE_PRIVACY, privacy_mode=True)
        return self._perform_deep_analysis(
            reason="window_focus",
            timeout=timeout,
            hwnd=int(hwnd),
        )

    # ── Status ──────────────────────────────────────────────────────────────
    def status(self) -> dict[str, Any]:
        with self._lock:
            state = self._state
            observation = self._last_observation
            started_at = self._started_at
            captures = self._captures
            analyses = self._analyses
            changes = self._changes
            capture_failures = self._capture_failures
            last_capture_at = self._last_capture_at
            last_observation_at = self._last_observation_at
            error = self._error
            emergency = self._emergency
        elapsed = max(0.0, time.time() - started_at) if started_at else 0.0
        return {
            "state": state,
            "running": state in {STATE_RUNNING, STATE_STARTING, STATE_DEGRADED, STATE_PRIVACY},
            "emergency_stopped": emergency,
            "privacy_mode": self._privacy.enabled,
            "error": error,
            "captures": captures,
            "analyses": analyses,
            "changes_detected": changes,
            "capture_failures": capture_failures,
            "last_capture_at": last_capture_at,
            "last_observation_at": last_observation_at,
            "last_deep_analysis_at": self._last_deep_at,
            "uptime_seconds": round(elapsed, 1),
            "capture_backend_error": self._capture.error,
            "ocr_available": self._ocr.available(),
            "ocr_error": self._ocr.error,
            "uia_available": self._inspector.available,
            "monitor_count": self._capture.monitor_count(),
            "monitors": [monitor.to_dict() for monitor in self._capture.monitors()],
            "change_threshold": round(self._detector.threshold, 3),
            "noise_floor": self._detector.noise_floor,
            "app_name": observation.app_name if observation else "",
            "window_title": observation.window_title if observation else "",
            "element_count": len(observation.elements) if observation else 0,
            "text_length": len(observation.text) if observation else 0,
            "problem_count": len(observation.problems) if observation else 0,
            "memory": self._memory.status(),
        }

    # ── Fast loop ───────────────────────────────────────────────────────────
    def _run_fast_loop(self) -> None:
        """Cheap monitoring loop: tiny captures + window polling only.

        The loop never runs OCR or UI Automation: those belong to the deep
        worker.  The polling interval adapts to the activity of the screen so
        a still desktop costs almost nothing.
        """
        next_capture = time.monotonic()
        next_window = time.monotonic()
        try:
            while not self._stop_event.is_set():
                if self._privacy.enabled:
                    with self._lock:
                        if self._state != STATE_PRIVACY:
                            self._state = STATE_PRIVACY
                    next_capture = time.monotonic() + 0.5
                    next_window = time.monotonic() + 0.5
                    self._stop_event.wait(0.25)
                    continue

                now = time.monotonic()
                if now >= next_capture:
                    self._capture_once()
                    next_capture = time.monotonic() + self._poll_interval()
                if now >= next_window:
                    self._last_window_poll = now
                    self._refresh_windows()
                    next_window = time.monotonic() + self._config.window_poll_interval

                sleep_for = min(next_capture, next_window) - time.monotonic()
                self._stop_event.wait(max(0.02, min(0.25, sleep_for)))
        except Exception as exc:  # pragma: no cover - defensive
            with self._lock:
                self._state = STATE_ERROR
                self._error = f"Vision engine loop failed: {exc}"
            self._bus.emit(EVENT_ENGINE_ERROR, {"error": str(exc)}, severity="error")

    def _poll_interval(self) -> float:
        """Adaptive polling interval: fast after a change, slower when idle."""
        with self._lock:
            if self._change_pending:
                return self._config.active_interval
            streak = self._idle_streak
        steps = min(2, streak // 4)
        interval = self._config.idle_interval * (2**steps)
        return float(min(self._config.max_idle_interval, max(0.05, interval)))

    def _capture_once(self) -> None:
        """Take one cheap signature capture and feed the change detector."""
        try:
            frame = self._capture.grab(want_full=False)
        except Exception as exc:
            frame = None
            self._handle_capture_error(str(exc))
        if frame is None:
            self._handle_capture_failure()
            return

        self._handle_capture_recovered()
        with self._lock:
            self._captures += 1
            self._last_capture_at = time.time()
            if self._state == STATE_STARTING:
                self._state = STATE_RUNNING

        result = self._detector.update(frame.signature)
        if result.changed:
            trigger = (
                self._config.base_change_threshold
                * self._config.deep_trigger_multiplier
            )
            significant = result.score >= trigger
            with self._lock:
                self._changes += 1
                self._idle_streak = 0
                self._stable_run = 0
                if significant:
                    self._change_pending = True
                    self._change_since = time.time()
            self._bus.emit(
                EVENT_SCREEN_CHANGED,
                {
                    "score": round(result.score, 3),
                    "threshold": round(result.threshold, 3),
                    "significant": significant,
                    "regions": [list(region) for region in result.regions],
                },
            )
            return

        with self._lock:
            self._idle_streak += 1
            if not self._change_pending:
                return
            self._stable_run += 1
            stable = self._stable_run >= self._config.stable_samples
            too_long = time.time() - self._change_since > self._config.deep_delay_max
        if stable or too_long:
            self._request_deep_analysis()

    # ── Deep loop ───────────────────────────────────────────────────────────
    def _run_deep_loop(self) -> None:
        while not self._stop_event.is_set():
            # `wait` returns False on timeout: only a real trigger may start
            # an analysis, otherwise the worker would poll continuously.
            triggered = self._deep_event.wait(timeout=0.5)
            if self._stop_event.is_set():
                break
            if not triggered:
                continue
            self._deep_event.clear()
            if self._privacy.enabled:
                continue
            try:
                self._perform_deep_analysis(reason="change")
            except Exception as exc:  # pragma: no cover - defensive
                with self._lock:
                    self._error = f"Deep analysis failed: {exc}"
                self._bus.emit(
                    EVENT_ENGINE_ERROR, {"error": str(exc)}, severity="warning"
                )

    def _request_deep_analysis(self) -> None:
        """Schedule a deep analysis, honouring the cooldown."""
        with self._lock:
            self._change_pending = False
            self._stable_run = 0
            if not self._config.deep_analysis:
                return
            if time.monotonic() - self._last_deep_at < self._config.deep_min_interval:
                # A deep analysis just ran: skip this one to keep the CPU low.
                return
        self._deep_event.set()

    # ── Analysis ────────────────────────────────────────────────────────────
    def _perform_deep_analysis(
        self,
        *,
        reason: str,
        timeout: float = 12.0,
        hwnd: int | None = None,
    ) -> ScreenObservation:
        """Full analysis: frame + windows + OCR + UI Automation."""
        deadline = time.monotonic() + max(1.0, float(timeout))
        with self._lock:
            self._last_deep_at = time.monotonic()
        frame = self._capture.grab(want_full=True)
        if frame is None:
            self._handle_capture_failure()
            with self._lock:
                self._state = STATE_DEGRADED
                self._error = self._capture.error or "Screen capture failed."
            observation = ScreenObservation(
                state=STATE_DEGRADED,
                note="The screen could not be captured.",
            )
            with self._lock:
                self._last_observation = observation
            return observation

        self._handle_capture_recovered()
        with self._lock:
            self._captures += 1
            self._last_capture_at = time.time()
            self._analyses += 1

        windows = self._safe_window_snapshot()
        window_diff = self._tracker.diff(windows)
        self._publish_window_events(window_diff, windows)

        elements: list[dict[str, Any]] = []
        if self._config.uia_enabled and hwnd is not None:
            target = int(hwnd)
        else:
            foreground = next((w for w in windows if w.foreground), None)
            target = foreground.hwnd if foreground else 0
        if self._config.uia_enabled and target:
            for element in self._inspector.inspect(target):
                elements.append(element.to_dict())
        elements = self._privacy.filter_elements(elements)

        text = ""
        text_blocks: list[dict[str, Any]] = []
        if (
            self._config.ocr_enabled
            and self._ocr_permitted
            and frame.has_image
        ):
            region = self._ocr_region(frame, windows)
            blocks = self._ocr.read(
                frame.image, origin=(frame.origin_x, frame.origin_y), region=region
            )
            text_blocks = self._privacy.redact_ocr(
                [block.to_dict() for block in blocks], elements
            )
            text = "\n".join(
                block["text"] for block in text_blocks if block.get("text")
            )
            text = self._privacy.redact_text(text)
            if len(text) > self._config.max_text_chars:
                text = text[: self._config.max_text_chars]

        titles = [window.title for window in windows if window.title]
        problems = detect_problems(titles, text)

        observation = self._build_observation(
            windows=windows,
            frame=frame,
            deep=True,
            change_score=self._detector.last_score,
            changed=True,
            elements=elements,
            text=text,
            text_blocks=text_blocks,
            problems=problems,
        )
        observation.note = reason
        with self._lock:
            self._last_observation = observation
            self._last_observation_at = time.time()
            self._state = STATE_RUNNING
            self._error = None
        self._memory.record(observation)
        self._bus.emit(
            EVENT_OBSERVATION,
            {
                "app_name": observation.app_name,
                "window_title": observation.window_title,
                "elements": len(observation.elements),
                "text_length": len(observation.text),
                "problems": len(observation.problems),
                "reason": reason,
            },
        )
        if observation.problems:
            self._bus.emit(
                EVENT_PROBLEM_DETECTED,
                {"problems": observation.problems},
                severity="warning",
            )
        if time.monotonic() > deadline:
            # The analysis itself succeeded; only the caller's patience ran out.
            observation.note = f"{observation.note} (deadline exceeded)".strip()
        return observation

    def _ocr_region(
        self, frame: Any, windows: list[WindowInfo]
    ) -> tuple[int, int, int, int] | None:
        """Region (in frame coordinates) the OCR should focus on.

        Restricting the OCR to the focused window keeps the native resolution
        — which Tesseract needs to read small text — while making the
        operation roughly three times faster than a full-desktop read.
        """
        if self._config.ocr_region != "foreground":
            return None
        foreground = next((w for w in windows if w.foreground), None)
        if foreground is None or not foreground.bounds:
            return None
        bounds = foreground.bounds
        try:
            left = int(bounds["left"]) - int(frame.origin_x)
            top = int(bounds["top"]) - int(frame.origin_y)
            width = int(bounds["width"])
            height = int(bounds["height"])
        except (KeyError, TypeError, ValueError):
            return None
        if width <= 0 or height <= 0:
            return None
        return (left, top, width, height)

    def _build_observation(
        self,
        *,
        windows: list[WindowInfo],
        frame: Any = None,
        deep: bool,
        change_score: float,
        changed: bool,
        elements: list[dict[str, Any]] | None = None,
        text: str = "",
        text_blocks: list[dict[str, Any]] | None = None,
        problems: list[dict[str, Any]] | None = None,
    ) -> ScreenObservation:
        foreground = next((w for w in windows if w.foreground), None)
        if foreground is None and windows:
            foreground = max(
                (w for w in windows if w.visible and not w.minimized),
                key=lambda w: (
                    w.bounds["width"] * w.bounds["height"] if w.bounds else 0
                ),
                default=None,
            )
        app_name = ""
        window_title = ""
        if foreground is not None:
            app_name = foreground.process_name or foreground.class_name or ""
            window_title = foreground.title
        monitors = [monitor.to_dict() for monitor in self._capture.monitors()]
        return ScreenObservation(
            timestamp=time.time(),
            app_name=app_name,
            window_title=window_title,
            foreground=foreground.to_dict() if foreground else None,
            windows=[window.to_dict() for window in windows],
            elements=list(elements or []),
            text=text,
            text_blocks=list(text_blocks or []),
            problems=list(problems or []),
            monitors=monitors,
            change_score=change_score,
            changed=changed,
            deep=deep,
            state=self.state,
            privacy_mode=self._privacy.enabled,
        )

    # ── Windows ─────────────────────────────────────────────────────────────
    def _safe_window_snapshot(self) -> list[WindowInfo]:
        try:
            return self._tracker.snapshot()
        except Exception:
            return []

    def _refresh_windows(self) -> None:
        windows = self._safe_window_snapshot()
        diff = self._tracker.diff(windows)
        self._publish_window_events(diff, windows)

    def _publish_window_events(
        self, diff: dict[str, Any], windows: list[WindowInfo]
    ) -> None:
        for window in diff.get("opened", [])[:6]:
            self._bus.emit(
                EVENT_WINDOW_OPENED,
                {"title": window.get("title", ""), "process": window.get("process_name", "")},
            )
        for window in diff.get("closed", [])[:6]:
            self._bus.emit(
                EVENT_WINDOW_CLOSED,
                {"title": window.get("title", ""), "process": window.get("process_name", "")},
            )
        if diff.get("focus_changed"):
            focused = next((w for w in windows if w.foreground), None)
            self._bus.emit(
                EVENT_WINDOW_FOCUSED,
                {
                    "title": focused.title if focused else "",
                    "process": focused.process_name if focused else "",
                },
            )

    # ── Failure handling ────────────────────────────────────────────────────
    def _handle_capture_failure(self) -> None:
        with self._lock:
            self._capture_failures += 1
            first = self._capture_failures == 1
            if self._state not in {STATE_EMERGENCY, STATE_STOPPED}:
                self._state = STATE_DEGRADED
            self._error = self._capture.error or "Screen capture failed."
        if first:
            self._detector.reset()
            self._bus.emit(
                EVENT_CAPTURE_LOST, {"error": self._error}, severity="warning"
            )

    def _handle_capture_error(self, message: str) -> None:
        with self._lock:
            self._error = message
        self._handle_capture_failure()

    def _handle_capture_recovered(self) -> None:
        with self._lock:
            recovered = self._capture_failures > 0
            if recovered:
                self._capture_failures = 0
            if self._state == STATE_DEGRADED:
                self._state = STATE_RUNNING
            self._error = None
        if recovered:
            self._detector.reset()
            self._bus.emit(EVENT_CAPTURE_RESTORED, {}, severity="notice")


__all__ = [
    "VisionEngine",
    "STATE_STOPPED",
    "STATE_STARTING",
    "STATE_RUNNING",
    "STATE_DEGRADED",
    "STATE_ERROR",
    "STATE_PRIVACY",
    "STATE_EMERGENCY",
]
