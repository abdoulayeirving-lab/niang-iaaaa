"""Local, deterministic analysis of Windows diagnostic reports."""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Iterable


_LOCK = threading.Lock()

REPAIR_CATALOG = {
    "flush_dns": {
        "action": "flush_dns",
        "category": "network",
        "label": "Vider le cache DNS",
        "permissions": "none",
        "risk": "low",
        "timeout_seconds": 30,
        "confirmation_required": True,
        "real_rollback": False,
        "keywords": ("dns", "resolver", "network", "réseau"),
    },
    "sfc_scannow": {
        "action": "sfc_scannow",
        "category": "system_files",
        "label": "Réparer les fichiers système avec SFC",
        "permissions": "administrator",
        "risk": "high",
        "timeout_seconds": 1800,
        "confirmation_required": True,
        "real_rollback": True,
        "keywords": ("integrity violation", "integrité", "system file", "fichier système", "sfc"),
    },
    "dism_restore_health": {
        "action": "dism_restore_health",
        "category": "windows",
        "label": "Réparer le magasin Windows avec DISM",
        "permissions": "administrator",
        "risk": "high",
        "timeout_seconds": 3600,
        "confirmation_required": True,
        "real_rollback": True,
        "keywords": ("component store", "magasin de composants", "repairable", "réparable", "dism", "corruption"),
    },
}


def _reports_directory() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else Path.home() / ".local" / "share"
    return root / "NIANG IA" / "diagnostics" / "reports"


def _read_reports(limit: int = 50) -> list[dict]:
    directory = _reports_directory()
    if not directory.is_dir():
        return []
    with _LOCK:
        try:
            files = sorted(directory.glob("windows-diagnostic-*.json"), reverse=True)
        except OSError:
            return []
    reports: list[dict] = []
    for path in files[:limit]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            data["_report_path"] = str(path)
            reports.append(data)
    return reports


def _normalize(text: object) -> str:
    value = str(text or "").casefold()
    value = re.sub(r"[^a-z0-9àâäçéèêëîïôöùûüÿœ]+", " ", value)
    return " ".join(value.split())


def _severity_rank(value: object) -> int:
    return {"low": 1, "medium": 2, "high": 3, "critical": 4}.get(
        str(value or "").casefold(), 0
    )


def _finding_signature(problem: object) -> str:
    normalized = _normalize(problem)
    tokens = [token for token in normalized.split() if len(token) >= 4]
    return " ".join(tokens[:8])


def _matching_repair(problem: str, category: str = "") -> str | None:
    haystack = _normalize(f"{category} {problem}")
    if any(word in haystack for word in ("dns", "resolver", "cache dns")):
        return "flush_dns"
    if any(word in haystack for word in ("component store", "magasin de composants", "dism", "repairable", "réparable")):
        return "dism_restore_health"
    if any(word in haystack for word in ("integrity violation", "violation d intégrité", "sfc", "system file", "fichier système")):
        return "sfc_scannow"
    return None


def analyze_report(report: dict | None = None) -> list[dict]:
    """Return explainable repair proposals; never executes a command."""
    reports = _read_reports()
    if report is not None and isinstance(report, dict):
        current = dict(report)
        current["_report_path"] = current.get("report_path")
        current_path = current.get("_report_path")
        if current_path:
            reports = [
                current
            ] + [
                item for item in reports
                if item.get("_report_path") != current_path
            ]
        else:
            reports = [current] + reports

    findings_by_signature: dict[str, list[dict]] = {}
    for historic in reports:
        for finding in historic.get("findings", []) or []:
            if not isinstance(finding, dict):
                continue
            signature = _finding_signature(finding.get("problem"))
            if signature:
                findings_by_signature.setdefault(signature, []).append({
                    "finding": finding,
                    "category": historic.get("category", ""),
                })

    proposals: list[dict] = []
    source_findings = (report or {}).get("findings", []) if isinstance(report, dict) else []
    for finding in source_findings:
        if not isinstance(finding, dict):
            continue
        problem = str(finding.get("problem") or "")
        category = (
            str(finding.get("category") or report.get("category", ""))
            if isinstance(report, dict)
            else ""
        )
        repair_id = _matching_repair(problem, category)
        if repair_id is None:
            continue
        signature = _finding_signature(problem)
        recurrence_count = len(findings_by_signature.get(signature, []))
        severity = str(finding.get("severity") or "medium").casefold()
        evidence_count = recurrence_count + (1 if finding.get("verification_state") == "observed" else 0)
        confidence = "suspicion"
        if evidence_count >= 3:
            confidence = "confirmed"
        elif evidence_count >= 2:
            confidence = "probable"
        catalog_entry = REPAIR_CATALOG[repair_id]
        proposals.append({
            "problem_id": signature[:120] or "unknown",
            "problem": problem[:240],
            "category": catalog_entry["category"],
            "severity": severity if _severity_rank(severity) else "medium",
            "confidence": confidence,
            "confidence_score": min(100, evidence_count * 25),
            "recurrence_count": recurrence_count,
            "likely_cause": str(finding.get("likely_cause") or "Cause not confirmed without further diagnostics.")[:300],
            "proposed_repair": repair_id,
            "solution": str(finding.get("recommended_solution") or catalog_entry["label"])[:300],
            "risk": catalog_entry["risk"],
            "permissions": catalog_entry["permissions"],
            "confirmation_required": True,
            "real_rollback": catalog_entry["real_rollback"],
            "authorization_required": True,
            "timeout_seconds": catalog_entry["timeout_seconds"],
        })

    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    proposals.sort(key=lambda item: (
        severity_order.get(item["severity"], 4),
        -item["confidence_score"],
        item["problem_id"],
    ))
    return proposals


def latest_repair_proposals(limit: int = 20) -> list[dict]:
    reports = _read_reports(limit=50)
    for report in reports[:1]:
        return analyze_report(report)[:limit]
    return []
