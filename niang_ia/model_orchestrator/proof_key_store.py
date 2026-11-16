from __future__ import annotations

import base64
import json
import os
import secrets
import sys
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_LOCAL_DATA_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
DEFAULT_PROOF_KEY_PATH = _LOCAL_DATA_DIR / "NIANG IA" / "workspace_proof_hmac.dpapi"


class ProofKeyError(RuntimeError):
    pass


class ProofKeyUnavailableError(ProofKeyError):
    """Key exists but cannot be read/decrypted or is invalid (fail closed; no silent regen)."""


class ProofKeyCorruptError(ProofKeyUnavailableError):
    pass


@dataclass(frozen=True)
class ProofKeyRecord:
    key_bytes: bytes
    created_at: str
    key_id: str
    path: Path


_lock = threading.Lock()


def _require_dpapi():
    if sys.platform != "win32":
        raise ProofKeyError("Protected workspace proof key storage requires Windows DPAPI.")
    import win32crypt  # noqa: F401
    return __import__("win32crypt")


def _dpapi_protect(data: bytes, description: str = "NIANG IA workspace proof key") -> bytes:
    win32crypt = _require_dpapi()
    return win32crypt.CryptProtectData(data, description, None, None, None, 0)


def _dpapi_unprotect(blob: bytes) -> bytes:
    win32crypt = _require_dpapi()
    try:
        return win32crypt.CryptUnprotectData(blob, None, None, None, 0)[1]
    except Exception as exc:
        raise ProofKeyUnavailableError("Workspace proof key is inaccessible or cannot be decrypted.") from exc


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _key_id(key_bytes: bytes) -> str:
    # Non-secret identifier for diagnostics/rotation tracking (no key material).
    import hashlib
    return hashlib.sha256(key_bytes).hexdigest()[:16]


def _encode_record(key_bytes: bytes, created_at: str | None = None) -> bytes:
    payload = {
        "version": 1,
        "key_b64": base64.b64encode(key_bytes).decode("ascii"),
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "key_id": _key_id(key_bytes),
        "purpose": "workspace_proof_hmac_sha256",
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _decode_record(raw: bytes, path: Path) -> ProofKeyRecord:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ProofKeyCorruptError("Workspace proof key storage is corrupt or has invalid format.") from exc
    if not isinstance(payload, dict):
        raise ProofKeyCorruptError("Workspace proof key storage has invalid format.")
    key_b64 = payload.get("key_b64")
    if not isinstance(key_b64, str) or not key_b64:
        raise ProofKeyCorruptError("Workspace proof key storage is missing key material.")
    try:
        key_bytes = base64.b64decode(key_b64.encode("ascii"), validate=True)
    except Exception as exc:
        raise ProofKeyCorruptError("Workspace proof key storage contains invalid key encoding.") from exc
    if len(key_bytes) < 32:
        raise ProofKeyCorruptError("Workspace proof key storage contains an invalid key.")
    created_at = str(payload.get("created_at", ""))
    kid = str(payload.get("key_id") or _key_id(key_bytes))
    return ProofKeyRecord(key_bytes=key_bytes, created_at=created_at, key_id=kid, path=path)


def load_key(path: Path | str = DEFAULT_PROOF_KEY_PATH) -> ProofKeyRecord:
    """Load persisted key. If file exists but is unreadable/corrupt, fail closed (no silent regen)."""
    p = Path(path)
    with _lock:
        try:
            blob = p.read_bytes()
        except FileNotFoundError as exc:
            raise ProofKeyError("Workspace proof key not found.") from exc
        decrypted = _dpapi_unprotect(blob)
        return _decode_record(decrypted, p)


def key_file_exists(path: Path | str = DEFAULT_PROOF_KEY_PATH) -> bool:
    return Path(path).exists()


def create_key(path: Path | str = DEFAULT_PROOF_KEY_PATH, *, overwrite: bool = False) -> ProofKeyRecord:
    """Create and persist a new key.

    If overwrite=False and file exists, raises (explicit rotation must choose overwrite=True).
    """
    p = Path(path)
    with _lock:
        if p.exists() and not overwrite:
            raise ProofKeyError("Workspace proof key already exists; explicit rotation required to replace it.")
        key_bytes = secrets.token_bytes(32)
        created_at = datetime.now(timezone.utc).isoformat()
        record = _encode_record(key_bytes, created_at=created_at)
        encrypted = _dpapi_protect(record)
        _atomic_write(p, encrypted)
        return ProofKeyRecord(key_bytes=key_bytes, created_at=created_at, key_id=_key_id(key_bytes), path=p)


def ensure_key_for_new_proofs(path: Path | str = DEFAULT_PROOF_KEY_PATH) -> ProofKeyRecord:
    """Return persisted key for signing new proofs.

    - If missing: create (first-time initialization).
    - If present: load; on any inaccessibility/corruption raise (never silently regenerate).
    """
    p = Path(path)
    with _lock:
        if p.exists():
            # load_key takes lock again but RLock not used; inline logic
            try:
                blob = p.read_bytes()
            except FileNotFoundError as exc:
                raise ProofKeyUnavailableError("Workspace proof key disappeared during access.") from exc
            decrypted = _dpapi_unprotect(blob)
            return _decode_record(decrypted, p)
        # First-time creation (no prior persisted key to preserve)
        key_bytes = secrets.token_bytes(32)
        created_at = datetime.now(timezone.utc).isoformat()
        record = _encode_record(key_bytes, created_at=created_at)
        encrypted = _dpapi_protect(record)
        _atomic_write(p, encrypted)
        return ProofKeyRecord(key_bytes=key_bytes, created_at=created_at, key_id=_key_id(key_bytes), path=p)


def rotate_key(path: Path | str = DEFAULT_PROOF_KEY_PATH) -> ProofKeyRecord:
    """Explicit rotation: replace key. Existing proofs signed with old key become unverifiable."""
    # Requires ability to write; does not read old key (rotation may be used after planned invalidation).
    return create_key(path, overwrite=True)


def load_key_for_verification(path: Path | str = DEFAULT_PROOF_KEY_PATH) -> ProofKeyRecord:
    """Load key for verifying proofs across restarts.

    - Missing key file: fail closed (cannot verify persisted proofs; request new inspection).
    - Unreadable/corrupt: fail closed (no silent regen).
    """
    p = Path(path)
    if not p.exists():
        raise ProofKeyUnavailableError("Workspace proof key is unavailable; a new inspection is required.")
    return load_key(p)
