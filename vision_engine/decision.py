"""The decision brain: observe, understand, verify — before and after acting.

Before an action the brain performs a full six-step check; after an action it
re-observes the screen and compares the result with what was expected.  Any
anomaly stops the loop instead of letting a broken action cascade.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .engine import VisionEngine
from .memory import VisualMemory
from .scene import ScreenObservation

DECISION_PROCEED = "proceed"
DECISION_CONFIRM = "confirm"
DECISION_ABORT = "abort"


@dataclass(slots=True)
class Decision:
    """Outcome of the pre-action analysis."""

    action: str = DECISION_PROCEED
    reason: str = ""
    risks: list[str] = field(default_factory=list)
    app_name: str = ""
    window_title: str = ""
    observation: dict[str, Any] = field(default_factory=dict)
    repeated_failure: bool = False
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def proceed(self) -> bool:
        return self.action == DECISION_PROCEED

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "risks": list(self.risks),
            "app_name": self.app_name,
            "window_title": self.window_title,
            "observation": dict(self.observation),
            "repeated_failure": self.repeated_failure,
            "context": dict(self.context),
        }


@dataclass(slots=True)
class VerificationResult:
    """Outcome of the post-action verification."""

    ok: bool = True
    reason: str = ""
    expected: str = ""
    matched: bool = False
    changes: dict[str, Any] = field(default_factory=dict)
    app_changed: bool = False
    window_changed: bool = False
    new_problems: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "expected": self.expected,
            "matched": self.matched,
            "changes": dict(self.changes),
            "app_changed": self.app_changed,
            "window_changed": self.window_changed,
            "new_problems": [dict(item) for item in self.new_problems],
        }


class DecisionEngine:
    """Applies the NIANG IA observe → decide → verify loop."""

    def __init__(
        self,
        engine: VisionEngine,
        *,
        memory: VisualMemory | None = None,
        risk_classifier: Callable[[str, dict], Any] | None = None,
        confirmation_checker: Callable[[str, dict], bool] | None = None,
        risk_names: Callable[[Any], str] | None = None,
    ) -> None:
        self._engine = engine
        self._memory = memory or engine.memory
        self._risk_classifier = risk_classifier
        self._confirmation_checker = confirmation_checker
        self._risk_names = risk_names or (lambda risk: getattr(risk, "name", str(risk)))
        self._lock = threading.RLock()
        self._last_decision: Decision | None = None
        self._last_verification: VerificationResult | None = None

    # ── Accessors ───────────────────────────────────────────────────────────
    @property
    def last_decision(self) -> Decision | None:
        return self._last_decision

    @property
    def last_verification(self) -> VerificationResult | None:
        return self._last_verification

    # ── Pre-action analysis ─────────────────────────────────────────────────
    def evaluate(
        self,
        *,
        tool: str,
        params: dict[str, Any] | None = None,
        mission_goal: str = "",
        mission_id: str | None = None,
        observe: bool = True,
        deep: bool = False,
    ) -> Decision:
        """Run the six-step check and decide whether the action may run."""
        params = dict(params or {})
        risks: list[str] = []

        # 1. Observe the screen.
        observation: ScreenObservation | None = None
        if observe:
            try:
                observation = self._engine.observe_now(deep=deep)
            except Exception as exc:
                decision = Decision(
                    action=DECISION_ABORT,
                    reason=f"The screen could not be observed, so the action was not executed: {exc}",
                    risks=["observation_failed"],
                )
                with self._lock:
                    self._last_decision = decision
                return decision

        # 2. Identify the application.
        app_name = observation.app_name if observation else ""
        window_title = observation.window_title if observation else ""

        # 3. Understand the context (what changed since the last observation).
        context = self._memory.diff(observation) if observation else {}

        # 4. Check the mission.
        mission_context = self._memory.mission_context(mission_id)
        if mission_id:
            self._memory.start_mission(mission_id, mission_goal)
        if mission_goal and app_name:
            context["mission_goal"] = mission_goal
            context["mission_context"] = mission_context

        # 5. Evaluate the risks.
        risk_level = None
        if self._risk_classifier is not None:
            try:
                risk_level = self._risk_classifier(tool, params)
            except Exception:
                risk_level = None
        if risk_level is not None:
            risks.append(self._risk_names(risk_level))

        repeated = self._memory.is_repeated_failure(tool, params)
        if repeated:
            risks.append("repeated_failure")

        # 6. Decide or ask for confirmation.
        needs_confirmation = False
        if self._confirmation_checker is not None:
            try:
                needs_confirmation = bool(self._confirmation_checker(tool, params))
            except Exception:
                needs_confirmation = True

        if repeated:
            decision = Decision(
                action=DECISION_ABORT,
                reason=(
                    "This exact action already failed in this session. "
                    "Change the approach instead of repeating it."
                ),
                risks=risks,
                app_name=app_name,
                window_title=window_title,
                observation=observation.to_dict() if observation else {},
                repeated_failure=True,
                context=context,
            )
        elif needs_confirmation:
            decision = Decision(
                action=DECISION_CONFIRM,
                reason=(
                    "The operation is sensitive and requires the user's explicit "
                    "approval before it runs."
                ),
                risks=risks,
                app_name=app_name,
                window_title=window_title,
                observation=observation.to_dict() if observation else {},
                context=context,
            )
        else:
            decision = Decision(
                action=DECISION_PROCEED,
                reason="The screen was observed and no blocking condition was found.",
                risks=risks,
                app_name=app_name,
                window_title=window_title,
                observation=observation.to_dict() if observation else {},
                context=context,
            )

        with self._lock:
            self._last_decision = decision
        return decision

    # ── Post-action verification ────────────────────────────────────────────
    def verify(
        self,
        *,
        before: ScreenObservation | dict[str, Any] | None = None,
        expected_text: str = "",
        expected_app: str = "",
        deep: bool = True,
        timeout: float = 10.0,
    ) -> VerificationResult:
        """Re-observe the screen and compare it with the expected outcome.

        Verification is a deep observation: it needs the detected text to be
        able to compare what was expected with what is now visible.
        """
        try:
            after = self._engine.observe_now(deep=deep, timeout=timeout)
        except Exception as exc:
            result = VerificationResult(
                ok=False,
                reason=f"The screen could not be re-observed after the action: {exc}",
                expected=expected_text,
            )
            with self._lock:
                self._last_verification = result
            return result

        before_dict = (
            before.to_dict() if isinstance(before, ScreenObservation) else dict(before or {})
        )
        changes = self._memory.diff(after)
        app_changed = bool(changes.get("app_changed"))
        window_changed = bool(changes.get("window_changed"))

        matched = False
        if expected_text:
            matched = after.has_text(expected_text)
        elif expected_app:
            matched = expected_app.casefold() in after.app_name.casefold()

        new_problems = list(after.problems)
        before_problems = {
            (item.get("kind"), item.get("message"))
            for item in before_dict.get("problems", [])
        }
        new_problems = [
            item
            for item in new_problems
            if (item.get("kind"), item.get("message")) not in before_problems
        ]

        if expected_text and not matched:
            ok = False
            reason = (
                f"The expected text {expected_text!r} is not visible on the screen "
                "after the action."
            )
        elif expected_app and not matched:
            ok = False
            reason = f"The expected application {expected_app!r} is not in the foreground."
        elif new_problems:
            ok = False
            reason = (
                f"{len(new_problems)} new problem(s) appeared after the action: "
                + ", ".join(str(item.get("message", ""))[:80] for item in new_problems[:3])
            )
        else:
            ok = True
            reason = "The screen matches the expected outcome."

        result = VerificationResult(
            ok=ok,
            reason=reason,
            expected=expected_text or expected_app,
            matched=matched,
            changes=changes,
            app_changed=app_changed,
            window_changed=window_changed,
            new_problems=new_problems,
        )
        with self._lock:
            self._last_verification = result
        return result

    def record_failure(
        self,
        tool: str,
        params: dict[str, Any],
        reason: str,
        *,
        mission_id: str | None = None,
    ) -> str:
        """Remember a failed action so it is not repeated blindly."""
        return self._memory.remember_failure(
            tool, params, reason, mission_id=mission_id
        )

    def status(self) -> dict[str, Any]:
        with self._lock:
            decision = self._last_decision
            verification = self._last_verification
        return {
            "last_decision": decision.to_dict() if decision else None,
            "last_verification": verification.to_dict() if verification else None,
            "memory": self._memory.status(),
        }


__all__ = [
    "DecisionEngine",
    "Decision",
    "VerificationResult",
    "DECISION_PROCEED",
    "DECISION_CONFIRM",
    "DECISION_ABORT",
]
