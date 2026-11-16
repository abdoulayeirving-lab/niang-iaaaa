from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping


DEFAULT_PROOF_TTL_SECONDS = 300
MAX_EVIDENCE_ENTRIES = 50
# Manifest limits: bounded inspection to avoid hashing large trees; errors -> refuse.
MANIFEST_MAX_FILES = 64
MANIFEST_MAX_FILE_BYTES = 256 * 1024
MANIFEST_MAX_TOTAL_BYTES = 1024 * 1024
MANIFEST_SAMPLE_DIR_ENTRIES = 40

# Legacy in-process fallback key (non-persisted). Used only when no persisted key store
# is available/configured (e.g. non-Windows environments) or when explicitly requested.
# Proofs signed with this key are not verifiable after process restart.
_EPHEMERAL_FALLBACK_KEY = secrets.token_bytes(32)

from .proof_key_store import (
    DEFAULT_PROOF_KEY_PATH,
    ProofKeyUnavailableError,
    ensure_key_for_new_proofs,
    load_key_for_verification,
)


@dataclass(frozen=True)
class WorkspaceProof:
    """Structured proof produced by a trusted workspace inspection.

    SECURITY: `trusted_source` is NOT sufficient authentication. A proof is valid only
    when its internal signature verifies against the verifier key and all checks pass.
    Callers must not construct/forge proofs; obtain them via TrustedWorkspaceVerifier.inspect().
    """

    trusted_source: str
    mission_id: str
    workspace_root: str
    observed_realpath: str
    observed_stat_signature: str
    mission_binding: str
    checked_at: float
    expires_at: float
    accessible: bool
    signature: str = ""
    manifest_hash: str = ""
    proof_version: int = 2
    evidence: dict[str, Any] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)

    @property
    def valid_window(self) -> bool:
        return self.expires_at > self.checked_at

    def to_dict(self) -> dict[str, Any]:
        # Serialized form is not trusted by itself; signature must still verify.
        return asdict(self)


def _sanitize_evidence(value: Any, depth: int = 0) -> Any:
    if depth > 4:
        return "[truncated]"
    if isinstance(value, dict):
        out = {}
        for k, v in list(value.items())[:MAX_EVIDENCE_ENTRIES]:
            key = str(k).lower()
            if any(tok in key for tok in ("secret", "token", "password", "key", "cookie", "authorization", "credential", "signature")):
                out[str(k)] = "[redacted]"
            else:
                out[str(k)] = _sanitize_evidence(v, depth + 1)
        return out
    if isinstance(value, list):
        return [_sanitize_evidence(v, depth + 1) for v in value[:MAX_EVIDENCE_ENTRIES]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str) and len(value) > 500:
            return value[:500] + "…"
        return value
    return str(value)


def _canonical_proof_payload(proof: WorkspaceProof | Mapping[str, Any]) -> bytes:
    """Canonical payload covered by signature (excludes signature and non-deterministic blobs)."""
    if isinstance(proof, WorkspaceProof):
        data = {
            "proof_version": proof.proof_version,
            "trusted_source": proof.trusted_source,
            "mission_id": proof.mission_id,
            "workspace_root": proof.workspace_root,
            "observed_realpath": proof.observed_realpath,
            "observed_stat_signature": proof.observed_stat_signature,
            "manifest_hash": proof.manifest_hash,
            "mission_binding": proof.mission_binding,
            "checked_at": proof.checked_at,
            "expires_at": proof.expires_at,
            "accessible": proof.accessible,
            "issues": list(proof.issues),
        }
    else:
        data = {
            "proof_version": int(proof.get("proof_version", 0)),
            "trusted_source": str(proof.get("trusted_source", "")),
            "mission_id": str(proof.get("mission_id", "")),
            "workspace_root": str(proof.get("workspace_root", "")),
            "observed_realpath": str(proof.get("observed_realpath", "")),
            "observed_stat_signature": str(proof.get("observed_stat_signature", "")),
            "manifest_hash": str(proof.get("manifest_hash", "")),
            "mission_binding": str(proof.get("mission_binding", "")),
            "checked_at": float(proof.get("checked_at", 0.0) or 0.0),
            "expires_at": float(proof.get("expires_at", 0.0) or 0.0),
            "accessible": bool(proof.get("accessible", False)),
            "issues": list(proof.get("issues") or []),
        }
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _compute_signature(key: bytes, proof: WorkspaceProof | Mapping[str, Any]) -> str:
    return hmac.new(key, _canonical_proof_payload(proof), hashlib.sha256).hexdigest()


def _hash_file(path: Path, max_bytes: int) -> str | None:
    h = hashlib.sha256()
    read = 0
    with path.open("rb") as f:
        while True:
            chunk = f.read(min(65536, max_bytes - read))
            if not chunk:
                break
            h.update(chunk)
            read += len(chunk)
            if read >= max_bytes:
                break
    # Indicate if truncated by including read length in digest domain separation
    h.update(f"|read={read}".encode("utf-8"))
    return h.hexdigest()


def _build_manifest(root: Path) -> tuple[str, list[dict[str, Any]], list[str], bool]:
    """Build a bounded manifest of direct child entries (depth 1) with content hashes.

    Returns (manifest_hash, manifest_entries, issues, ok). On inspection errors or limit
    exceedance, ok is False and callers must refuse by default.
    Guarantees (documented, best-effort within limits): detects direct entry add/remove/rename,
    file content changes for hashed files (up to limits), symlink presence, and inaccessible
    entries. Does NOT guarantee detection of changes in subdirectories beyond their direct
    entry metadata, files larger than limits (hashed partially/not included per policy),
    or concurrent modifications during inspection (TOCTOU window).
    """
    issues: list[str] = []
    entries: list[dict[str, Any]] = []
    total_hashed = 0
    try:
        children = sorted(root.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return "", [], ["manifest_listing_failed"], False

    if len(children) > MANIFEST_SAMPLE_DIR_ENTRIES:
        issues.append("manifest_entry_limit_exceeded")
        # Still record capped set deterministically for evidence; but manifest is incomplete -> refuse.
        children = children[:MANIFEST_SAMPLE_DIR_ENTRIES]

    for child in children:
        try:
            is_symlink = child.is_symlink()
            # Use lstat-equivalent info for symlink detection; follow only for type/size when safe.
            lst = child.lstat() if hasattr(child, "lstat") else child.stat()
            item: dict[str, Any] = {
                "name": child.name,
                "is_dir": child.is_dir() and not is_symlink,
                "is_symlink": bool(is_symlink),
                "size": int(getattr(lst, "st_size", 0)),
                "mtime_ns": int(getattr(lst, "st_mtime_ns", 0)),
            }
            if is_symlink:
                issues.append("manifest_contains_symlink")
                # Record target text only as sanitized marker? avoid leaking; just flag.
                item["symlink"] = True
            elif child.is_file():
                size = item["size"]
                if size > MANIFEST_MAX_FILE_BYTES:
                    issues.append("manifest_file_too_large")
                    item["hash"] = None
                elif total_hashed + size > MANIFEST_MAX_TOTAL_BYTES:
                    issues.append("manifest_total_limit_exceeded")
                    item["hash"] = None
                elif len([e for e in entries if "hash" in e]) >= MANIFEST_MAX_FILES:
                    issues.append("manifest_hash_count_exceeded")
                    item["hash"] = None
                else:
                    digest = _hash_file(child, MANIFEST_MAX_FILE_BYTES)
                    item["hash"] = digest
                    total_hashed += size
            elif child.is_dir():
                # Directory identity via its own stat signature (content of subdir not fully hashed).
                dst = child.stat()
                item["dir_sig"] = hashlib.sha256(
                    f"{getattr(dst,'st_dev',0)}:{getattr(dst,'st_ino',0)}:{int(dst.st_mtime_ns)}:{dst.st_mode}".encode("utf-8")
                ).hexdigest()
            entries.append(item)
        except OSError:
            issues.append("manifest_entry_inspection_failed")
            entries.append({"name": getattr(child, "name", "?"), "error": True})

    # Any inspection/limit issue means the manifest cannot be trusted as complete -> refuse by default.
    fatal = any(i in {
        "manifest_listing_failed",
        "manifest_entry_inspection_failed",
        "manifest_entry_limit_exceeded",
        "manifest_file_too_large",
        "manifest_total_limit_exceeded",
        "manifest_hash_count_exceeded",
    } for i in issues)
    if any(e.get("error") for e in entries):
        fatal = True
    manifest_hash = hashlib.sha256(
        json.dumps(entries, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    return manifest_hash, entries, issues, (not fatal)


def _safe_stat_signature(path: Path) -> str:
    st = path.stat()
    dev = getattr(st, "st_dev", 0)
    ino = getattr(st, "st_ino", 0)
    payload = f"{dev}:{ino}:{int(st.st_mtime_ns)}:{st.st_size}:{st.st_mode}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class TrustedWorkspaceVerifier:
    """Performs real workspace inspection and issues signed structured proofs.

    This component is isolated and opt-in. Proofs are HMAC-signed with a verifier key
    (never logged/serialized). `trusted_source` alone is not authentication.

    Key handling (8A.2):
    - If `secret_key` is provided, it is used directly (caller-managed; not persisted here).
    - Else, a DPAPI-protected persisted key store is used when available (Windows):
      * inspect/new proofs: load existing key or create on first use; if key file exists but
        is inaccessible/corrupt, fail closed (never silently regenerate).
      * validation: load existing key; if missing/inaccessible/corrupt, fail closed (new inspection required).
    - If DPAPI persistence is unavailable (e.g. non-Windows without injection), a non-persisted
      in-process fallback key is used (proofs not verifiable after restart).
    """

    TRUSTED_SOURCE = "niang.trusted_workspace_verifier.v2"

    def __init__(
        self,
        ttl_seconds: int = DEFAULT_PROOF_TTL_SECONDS,
        secret_key: bytes | None = None,
        key_store_path: str | os.PathLike[str] | None = None,
        use_persisted_key: bool = True,
    ):
        self.ttl_seconds = max(1, int(ttl_seconds))
        self._explicit_secret_key = bytes(secret_key) if secret_key is not None else None
        self._key_store_path = Path(key_store_path) if key_store_path is not None else DEFAULT_PROOF_KEY_PATH
        self._use_persisted_key = bool(use_persisted_key)
        self._key_id: str | None = None
        self._key_source: str = "explicit" if secret_key is not None else ("persisted" if use_persisted_key else "ephemeral")
        # Resolved lazily per operation to enforce fail-closed semantics on load errors.

    def _resolve_key(self, *, for_signing: bool) -> bytes:
        if self._explicit_secret_key is not None:
            self._key_id = hashlib.sha256(self._explicit_secret_key).hexdigest()[:16]
            self._key_source = "explicit"
            return self._explicit_secret_key
        if self._use_persisted_key and os.name == "nt":
            try:
                if for_signing:
                    record = ensure_key_for_new_proofs(self._key_store_path)
                else:
                    record = load_key_for_verification(self._key_store_path)
                self._key_id = record.key_id
                self._key_source = "persisted_dpapi"
                return record.key_bytes
            except ProofKeyUnavailableError:
                raise
            except Exception:
                # Non-Windows DPAPI module issues or unexpected errors: do not silently replace key;
                # fail closed for persisted mode.
                raise ProofKeyUnavailableError("Workspace proof key is unavailable or inaccessible.")
        # Fallback (non-persisted) when DPAPI persistence not used/available.
        self._key_id = hashlib.sha256(_EPHEMERAL_FALLBACK_KEY).hexdigest()[:16]
        self._key_source = "ephemeral_fallback"
        return _EPHEMERAL_FALLBACK_KEY

    def inspect(
        self,
        workspace_root: str | os.PathLike[str],
        *,
        mission_id: str,
        expected_mission_markers: dict[str, Any] | None = None,
        now: float | None = None,
    ) -> WorkspaceProof:
        ts = float(now if now is not None else time.time())
        expires = ts + self.ttl_seconds
        root = Path(workspace_root)
        issues: list[str] = []
        evidence: dict[str, Any] = {"checked_at": ts}
        accessible = False
        observed_realpath = ""
        observed_stat_signature = ""
        mission_binding = ""
        manifest_hash = ""
        manifest_entries: list[dict[str, Any]] = []

        try:
            resolved = root.expanduser().resolve(strict=True)
            observed_realpath = str(resolved)
            evidence["realpath"] = observed_realpath
            evidence["exists"] = resolved.exists()
            evidence["is_dir"] = resolved.is_dir()
            if not resolved.is_dir():
                issues.append("workspace_not_directory")
            else:
                accessible = True
                observed_stat_signature = _safe_stat_signature(resolved)
                manifest_hash, manifest_entries, m_issues, m_ok = _build_manifest(resolved)
                issues.extend(m_issues)
                if not m_ok:
                    issues.append("manifest_incomplete_or_untrusted")
                evidence["entries_sample"] = _sanitize_evidence(manifest_entries[:20])
                evidence["entry_count_sampled"] = len(manifest_entries)
                evidence["manifest_hash"] = manifest_hash
        except FileNotFoundError:
            issues.append("workspace_missing")
            evidence["exists"] = False
        except OSError as exc:
            issues.append("workspace_inaccessible")
            evidence["os_error"] = str(exc)
        except Exception:
            issues.append("workspace_inspection_error")

        mission_binding = hashlib.sha256(f"{mission_id}|{observed_realpath}".encode("utf-8")).hexdigest()
        evidence["mission_id"] = mission_id
        evidence["mission_binding"] = mission_binding

        markers = expected_mission_markers or {}
        if markers:
            expected_ws = markers.get("workspace_root") or markers.get("workspace_realpath")
            if expected_ws:
                try:
                    expected_norm = str(Path(str(expected_ws)).expanduser().resolve(strict=False))
                except Exception:
                    expected_norm = str(expected_ws)
                if observed_realpath and observed_realpath != expected_norm:
                    issues.append("workspace_mismatch")
            expected_mission = markers.get("mission_id")
            if expected_mission and str(expected_mission) != str(mission_id):
                issues.append("mission_mismatch")
            marker_file = markers.get("mission_marker_file")
            expected_content = markers.get("mission_marker_content")
            if marker_file and observed_realpath:
                try:
                    mf = (Path(observed_realpath) / str(marker_file)).resolve(strict=True)
                    if Path(observed_realpath) not in mf.parents and mf != Path(observed_realpath):
                        issues.append("mission_marker_outside_workspace")
                    else:
                        content = mf.read_text(encoding="utf-8", errors="replace")[:2000]
                        evidence["mission_marker_file"] = str(marker_file)
                        evidence["mission_marker_found"] = True
                        if expected_content is not None and str(expected_content) not in content:
                            issues.append("mission_marker_mismatch")
                except OSError:
                    issues.append("mission_marker_missing")
                    evidence["mission_marker_found"] = False

        proof = WorkspaceProof(
            trusted_source=self.TRUSTED_SOURCE,
            mission_id=str(mission_id or ""),
            workspace_root=str(workspace_root),
            observed_realpath=observed_realpath,
            observed_stat_signature=observed_stat_signature,
            mission_binding=mission_binding,
            checked_at=ts,
            expires_at=expires,
            accessible=accessible,
            signature="",
            manifest_hash=manifest_hash,
            proof_version=2,
            evidence=_sanitize_evidence(evidence),
            issues=issues,
        )
        try:
            key = self._resolve_key(for_signing=True)
            sig = _compute_signature(key, proof)
        except Exception:
            # Fail closed: never issue a usable proof without a verifiable signing key.
            sig = ""
            if "proof_signing_key_unavailable" not in proof.issues:
                proof = WorkspaceProof(
                    trusted_source=proof.trusted_source,
                    mission_id=proof.mission_id,
                    workspace_root=proof.workspace_root,
                    observed_realpath=proof.observed_realpath,
                    observed_stat_signature=proof.observed_stat_signature,
                    mission_binding=proof.mission_binding,
                    checked_at=proof.checked_at,
                    expires_at=proof.expires_at,
                    accessible=proof.accessible,
                    signature="",
                    manifest_hash=proof.manifest_hash,
                    proof_version=proof.proof_version,
                    evidence=proof.evidence,
                    issues=list(proof.issues) + ["proof_signing_key_unavailable"],
                )
        return WorkspaceProof(
            trusted_source=proof.trusted_source,
            mission_id=proof.mission_id,
            workspace_root=proof.workspace_root,
            observed_realpath=proof.observed_realpath,
            observed_stat_signature=proof.observed_stat_signature,
            mission_binding=proof.mission_binding,
            checked_at=proof.checked_at,
            expires_at=proof.expires_at,
            accessible=proof.accessible,
            signature=sig,
            manifest_hash=proof.manifest_hash,
            proof_version=proof.proof_version,
            evidence=proof.evidence,
            issues=proof.issues,
        )

    def verify_signature(self, proof: WorkspaceProof | Mapping[str, Any]) -> bool:
        try:
            sig = proof.signature if isinstance(proof, WorkspaceProof) else str(proof.get("signature", ""))
            key = self._resolve_key(for_signing=False)
            expected = _compute_signature(key, proof)
            return bool(sig) and hmac.compare_digest(str(sig), expected)
        except Exception:
            return False

    @property
    def key_id(self) -> str | None:
        # Safe non-secret identifier, if resolved.
        return self._key_id


def _coerce_proof(proof: Any) -> WorkspaceProof | None:
    if proof is None:
        return None
    if isinstance(proof, WorkspaceProof):
        return proof
    if isinstance(proof, Mapping):
        try:
            return WorkspaceProof(
                trusted_source=str(proof.get("trusted_source", "")),
                mission_id=str(proof.get("mission_id", "")),
                workspace_root=str(proof.get("workspace_root", "")),
                observed_realpath=str(proof.get("observed_realpath", "")),
                observed_stat_signature=str(proof.get("observed_stat_signature", "")),
                mission_binding=str(proof.get("mission_binding", "")),
                checked_at=float(proof.get("checked_at", 0.0) or 0.0),
                expires_at=float(proof.get("expires_at", 0.0) or 0.0),
                accessible=bool(proof.get("accessible", False)),
                signature=str(proof.get("signature", "")),
                manifest_hash=str(proof.get("manifest_hash", "")),
                proof_version=int(proof.get("proof_version", 1) or 1),
                evidence=dict(proof.get("evidence") or {}),
                issues=list(proof.get("issues") or []),
            )
        except Exception:
            return None
    return None


def validate_proof(
    proof: WorkspaceProof | Mapping[str, Any] | None,
    *,
    mission_id: str,
    workspace_root: str | os.PathLike[str] | None = None,
    now: float | None = None,
    reinspect: bool = True,
    verifier: TrustedWorkspaceVerifier | None = None,
) -> tuple[bool, list[str]]:
    """Validate a verifier-issued, signed proof. Fail closed on any uncertainty/error."""
    coerced = _coerce_proof(proof)
    if coerced is None:
        return False, ["proof_missing_or_invalid"]

    issues: list[str] = []
    ts = float(now if now is not None else time.time())
    v = verifier or TrustedWorkspaceVerifier()  # uses default/persisted key context
    # Signature/authentication: required. trusted_source string is insufficient.
    try:
        sig_ok = v.verify_signature(coerced)
    except Exception:
        sig_ok = False
        issues.append("proof_verification_key_unavailable")
    if not sig_ok:
        issues.append("proof_signature_invalid")
    if coerced.trusted_source != TrustedWorkspaceVerifier.TRUSTED_SOURCE:
        issues.append("untrusted_proof_source")
    if coerced.proof_version < 2:
        issues.append("proof_version_unsupported")

    if not coerced.mission_id or str(coerced.mission_id) != str(mission_id):
        issues.append("mission_mismatch")
    if not coerced.observed_realpath or not coerced.observed_stat_signature or not coerced.manifest_hash:
        issues.append("proof_missing_real_inspection")
    if not coerced.accessible:
        issues.append("workspace_not_accessible")
    if coerced.expires_at <= ts:
        issues.append("proof_expired")
    if coerced.issues:
        issues.extend([f"proof_issue:{i}" for i in coerced.issues])

    if workspace_root is not None and coerced.observed_realpath:
        try:
            expected = str(Path(workspace_root).expanduser().resolve(strict=False))
            if expected != coerced.observed_realpath:
                issues.append("workspace_mismatch")
        except Exception:
            issues.append("workspace_mismatch")

    # Re-inspection/consistency checks: any error -> refuse.
    if reinspect and coerced.observed_realpath and "proof_expired" not in issues and "proof_signature_invalid" not in issues:
        try:
            p = Path(coerced.observed_realpath)
            if not p.exists() or not p.is_dir():
                issues.append("workspace_missing_or_inaccessible")
            else:
                current_sig = _safe_stat_signature(p)
                if coerced.observed_stat_signature and current_sig != coerced.observed_stat_signature:
                    issues.append("workspace_identity_changed")
                # Recompute manifest to detect content/entry changes within manifest guarantees.
                mhash, _, m_issues, m_ok = _build_manifest(p)
                if (not m_ok) or m_issues:
                    issues.append("workspace_reinspect_failed_or_unsafe")
                elif mhash != coerced.manifest_hash:
                    issues.append("workspace_manifest_changed")
        except OSError:
            issues.append("workspace_missing_or_inaccessible")
        except Exception:
            issues.append("workspace_reinspect_failed_or_unsafe")

    deduped = []
    seen = set()
    for i in issues:
        if i not in seen:
            seen.add(i)
            deduped.append(i)
    return (len(deduped) == 0), deduped


def authorize_risky_resume_or_write(
    *,
    mission_id: str,
    workspace_root: str | os.PathLike[str] | None,
    proof: WorkspaceProof | Mapping[str, Any] | None,
    handoff: Any | None = None,
    current_step_state: str = "unknown",
    allow_without_proof: bool = False,
    now: float | None = None,
    verifier: TrustedWorkspaceVerifier | None = None,
) -> tuple[bool, list[str]]:
    """Default-refuse gate for risky resume/write.

    - Requires a valid, signed, trusted workspace proof (real inspection) unless explicitly
      allowed for non-sensitive legacy paths (allow_without_proof=False by default).
    - Refuses unknown/uncertain/in-progress states by default.
    """
    issues: list[str] = []
    state = str(current_step_state or "unknown")
    if state in {"unknown", "in_progress", "running", "unknown_unverified", "handoff_pending_verification"}:
        issues.append("state_not_verified_for_risky_action")
    if handoff is not None:
        try:
            from .continuity import has_uncertain_or_unverified_actions
            if has_uncertain_or_unverified_actions(handoff):
                issues.append("handoff_contains_uncertain_or_unverified_actions")
        except Exception:
            issues.append("handoff_validation_unavailable")
    if allow_without_proof and not issues:
        return True, []
    ok, proof_issues = validate_proof(
        proof, mission_id=mission_id, workspace_root=workspace_root, now=now, verifier=verifier
    )
    issues.extend(proof_issues)
    if not ok:
        return False, issues
    if any(i in {"state_not_verified_for_risky_action", "handoff_contains_uncertain_or_unverified_actions"} for i in issues):
        return False, issues
    return (len(issues) == 0), issues
