from __future__ import annotations

from collections.abc import Sequence
from typing import Any


_TEST_CHECKS = {
    "python-tests", "python-unittest", "npm-test", "go-test", "cargo-test",
    "dotnet-test", "mvn-test", "gradle-test",
}
_BUILD_CHECKS = {
    "python-compile", "npm-build", "tsc-check", "go-build", "cargo-check",
    "cargo-build", "dotnet-build", "mvn-compile", "gradle-build",
}
_WEB_SKILLS = {
    "premium-web-design", "advanced-ui-ux", "creative-motion",
    "immersive-3d-web", "responsive-mobile-first", "frontend-mastery",
    "awwwards-level-web-design", "advanced-ui-ux-responsive",
    "gsap-animation-mastery", "framer-motion-mastery",
    "threejs-webgl-mastery", "advanced-css-design-systems",
    "performance-optimization",
}
_WEB_QUALITY_DIMENSIONS = (
    ("visual_design", "Visual design"),
    ("responsive", "Responsive behavior"),
    ("accessibility", "Accessibility"),
    ("interactions", "Interactive behavior"),
    ("performance", "Performance"),
)


def evaluate_quality_gate(
    goal: str,
    checks: Sequence[dict[str, Any]],
    *,
    selected_skill_ids: Sequence[str] = (),
) -> dict[str, Any]:
    latest: dict[str, dict[str, Any]] = {}
    explicit: dict[str, dict[str, Any]] = {}
    for item in checks:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        status = item.get("status")
        evidence = item.get("evidence")
        if not isinstance(name, str) or not name.strip():
            continue
        if (
            not isinstance(status, str)
            or status not in {"PASS", "FAIL"}
            or not isinstance(evidence, str)
            or not evidence.strip()
        ):
            continue
        if name in {"visual_design", "responsive", "accessibility", "interactions", "performance", "security"}:
            explicit[name] = {"status": status, "evidence": [evidence.strip()]}
        elif name in _TEST_CHECKS or name in _BUILD_CHECKS:
            latest[name] = {"status": status, "evidence": [evidence.strip()]}

    required = [
        ("tests", "Automated tests", _evidence_for(latest, _TEST_CHECKS)),
        ("build", "Build/type check", _evidence_for(latest, _BUILD_CHECKS)),
        ("security", "Security", explicit.get("security")),
    ]
    if _is_web_mission(goal, selected_skill_ids):
        required.extend(
            (key, label, explicit.get(key))
            for key, label in _WEB_QUALITY_DIMENSIONS
        )

    evaluated = []
    for key, label, evidence in required:
        evaluated.append({
            "id": key,
            "name": label,
            "status": evidence["status"] if evidence else "NOT_TESTED",
            "evidence": evidence["evidence"] if evidence else [],
        })
    if any(item["status"] == "FAIL" for item in evaluated):
        overall = "FAIL"
    elif all(item["status"] == "PASS" for item in evaluated):
        overall = "PASS"
    else:
        overall = "NOT_TESTED"
    return {"status": overall, "checks": evaluated}


def format_quality_gate(report: dict[str, Any]) -> str:
    status = report.get("status", "NOT_TESTED")
    label = "NON TESTÉ" if status == "NOT_TESTED" else str(status)
    lines = [f"QUALITY GATE: {label}"]
    checks = report.get("checks", [])
    if isinstance(checks, list):
        for item in checks:
            if not isinstance(item, dict):
                continue
            check_status = item.get("status", "NOT_TESTED")
            check_label = "NON TESTÉ" if check_status == "NOT_TESTED" else str(check_status)
            evidence = item.get("evidence", [])
            evidence_text = (
                ", ".join(value for value in evidence if isinstance(value, str))
                if isinstance(evidence, list)
                else ""
            )
            suffix = f" — {evidence_text}" if evidence_text else ""
            lines.append(f"- {item.get('name', item.get('id', 'Check'))}: {check_label}{suffix}")
    return "\n".join(lines)


def _evidence_for(
    checks: dict[str, dict[str, Any]],
    accepted_names: set[str],
) -> dict[str, Any] | None:
    relevant = [value for name, value in checks.items() if name in accepted_names]
    if not relevant:
        return None
    status = "FAIL" if any(item["status"] == "FAIL" for item in relevant) else "PASS"
    return {
        "status": status,
        "evidence": [name for name in checks if name in accepted_names],
    }


def _is_web_mission(goal: str, selected_skill_ids: Sequence[str]) -> bool:
    normalized_goal = goal.casefold()
    return bool(_WEB_SKILLS.intersection(selected_skill_ids)) or any(
        phrase in normalized_goal
        for phrase in ("site web", "website", "web app", "application web", "landing page")
    )
