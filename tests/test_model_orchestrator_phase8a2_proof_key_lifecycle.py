from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from niang_ia.model_orchestrator.proof_key_store import (
    ProofKeyCorruptError,
    ProofKeyUnavailableError,
    create_key,
    ensure_key_for_new_proofs,
    key_file_exists,
    load_key,
    load_key_for_verification,
    rotate_key,
)
from niang_ia.model_orchestrator.workspace_verification import (
    TrustedWorkspaceVerifier,
    validate_proof,
)


def _dpapi_available() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import win32crypt  # noqa: F401
        return True
    except Exception:
        return False


@unittest.skipUnless(_dpapi_available(), "Windows DPAPI (win32crypt) required")
class Phase8A2SimulatedKeyAndLifecycleTests(unittest.TestCase):
    """SIMULATED: controlled key/lifecycle scenarios using real DPAPI store in temp paths."""

    def test_missing_key_for_verification_refused(self):
        with tempfile.TemporaryDirectory() as td:
            key_path = Path(td) / "wk.dpapi"
            ws = Path(td) / "ws"
            ws.mkdir()
            # Proof signed with an explicit key (no persisted file for verifier)
            signer = TrustedWorkspaceVerifier(key_store_path=key_path, use_persisted_key=False)
            proof = signer.inspect(ws, mission_id="m1")
            verifier = TrustedWorkspaceVerifier(key_store_path=key_path, use_persisted_key=True)
            ok, issues = validate_proof(proof, mission_id="m1", workspace_root=ws, verifier=verifier, reinspect=False)
            self.assertFalse(ok)
            self.assertTrue("proof_signature_invalid" in issues or "proof_verification_key_unavailable" in issues)

    def test_corrupt_key_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            key_path = Path(td) / "wk.dpapi"
            key_path.parent.mkdir(parents=True, exist_ok=True)
            key_path.write_bytes(b"not-dpapi")
            with self.assertRaises(ProofKeyUnavailableError):
                load_key(key_path)
            with self.assertRaises(ProofKeyUnavailableError):
                load_key_for_verification(key_path)

    def test_wrong_key_rejects_proof(self):
        with tempfile.TemporaryDirectory() as td:
            key_a = Path(td) / "a.dpapi"
            key_b = Path(td) / "b.dpapi"
            ws = Path(td) / "ws"
            ws.mkdir()
            va = TrustedWorkspaceVerifier(key_store_path=key_a, use_persisted_key=True)
            vb = TrustedWorkspaceVerifier(key_store_path=key_b, use_persisted_key=True)
            proof = va.inspect(ws, mission_id="m1")
            ok, issues = validate_proof(proof, mission_id="m1", workspace_root=ws, verifier=vb, reinspect=False)
            self.assertFalse(ok)
            self.assertIn("proof_signature_invalid", issues)

    def test_explicit_rotation_invalidates_old_proofs(self):
        with tempfile.TemporaryDirectory() as td:
            key_path = Path(td) / "wk.dpapi"
            ws = Path(td) / "ws"
            ws.mkdir()
            v = TrustedWorkspaceVerifier(key_store_path=key_path, use_persisted_key=True)
            proof = v.inspect(ws, mission_id="m1")
            ok1, _ = validate_proof(proof, mission_id="m1", workspace_root=ws, verifier=v, reinspect=False)
            self.assertTrue(ok1)
            rotate_key(key_path)  # explicit rotation
            v2 = TrustedWorkspaceVerifier(key_store_path=key_path, use_persisted_key=True)
            ok2, issues2 = validate_proof(proof, mission_id="m1", workspace_root=ws, verifier=v2, reinspect=False)
            self.assertFalse(ok2)
            self.assertIn("proof_signature_invalid", issues2)

    def test_expired_proof_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            key_path = Path(td) / "wk.dpapi"
            ws = Path(td) / "ws"
            ws.mkdir()
            v = TrustedWorkspaceVerifier(ttl_seconds=1, key_store_path=key_path, use_persisted_key=True)
            proof = v.inspect(ws, mission_id="m1", now=1000.0)
            ok, issues = validate_proof(proof, mission_id="m1", workspace_root=ws, verifier=v, now=1005.0, reinspect=False)
            self.assertFalse(ok)
            self.assertIn("proof_expired", issues)

    def test_proof_other_mission_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            key_path = Path(td) / "wk.dpapi"
            ws = Path(td) / "ws"
            ws.mkdir()
            v = TrustedWorkspaceVerifier(key_store_path=key_path, use_persisted_key=True)
            proof = v.inspect(ws, mission_id="m1")
            ok, issues = validate_proof(proof, mission_id="m2", workspace_root=ws, verifier=v, reinspect=False)
            self.assertFalse(ok)
            self.assertIn("mission_mismatch", issues)

    def test_inaccessible_key_no_silent_regeneration(self):
        with tempfile.TemporaryDirectory() as td:
            key_path = Path(td) / "wk.dpapi"
            ws = Path(td) / "ws"
            ws.mkdir()
            # Create valid key first
            ensure_key_for_new_proofs(key_path)
            self.assertTrue(key_file_exists(key_path))
            # Corrupt it to simulate inaccessible/decrypt failure
            key_path.write_bytes(b"corrupt")
            v = TrustedWorkspaceVerifier(key_store_path=key_path, use_persisted_key=True)
            proof = v.inspect(ws, mission_id="m1")
            # Must not issue a usable signed proof when key exists but is inaccessible
            ok, issues = validate_proof(proof, mission_id="m1", workspace_root=ws, verifier=v, reinspect=False)
            self.assertFalse(ok)
            self.assertTrue(any(i in issues for i in ("proof_signature_invalid", "proof_verification_key_unavailable")) or any(i.startswith("proof_issue:") for i in issues))
            # File still present/corrupt; no silent replacement with a fresh valid store
            self.assertEqual(key_path.read_bytes(), b"corrupt")

    def test_fabricated_proof_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            key_path = Path(td) / "wk.dpapi"
            ws = Path(td) / "ws"
            ws.mkdir()
            v = TrustedWorkspaceVerifier(key_store_path=key_path, use_persisted_key=True)
            real = v.inspect(ws, mission_id="m1")
            fabricated = dict(real.to_dict())
            fabricated["signature"] = "00" * 32
            ok, issues = validate_proof(fabricated, mission_id="m1", workspace_root=ws, verifier=v, reinspect=False)
            self.assertFalse(ok)
            self.assertIn("proof_signature_invalid", issues)

    def test_replay_after_workspace_change_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            key_path = Path(td) / "wk.dpapi"
            ws = Path(td) / "ws"
            ws.mkdir()
            (ws / "f.txt").write_text("a", encoding="utf-8")
            v = TrustedWorkspaceVerifier(key_store_path=key_path, use_persisted_key=True)
            proof = v.inspect(ws, mission_id="m1")
            (ws / "f.txt").write_text("b", encoding="utf-8")
            ok, issues = validate_proof(proof, mission_id="m1", workspace_root=ws, verifier=v, reinspect=True)
            self.assertFalse(ok)
            self.assertTrue("workspace_manifest_changed" in issues or "workspace_reinspect_failed_or_unsafe" in issues or "workspace_identity_changed" in issues)

    def test_explicit_invalidation_via_rotation(self):
        # Explicit invalidation model: rotate key so previously issued proofs cannot be verified.
        with tempfile.TemporaryDirectory() as td:
            key_path = Path(td) / "wk.dpapi"
            ws = Path(td) / "ws"
            ws.mkdir()
            v = TrustedWorkspaceVerifier(key_store_path=key_path, use_persisted_key=True)
            p1 = v.inspect(ws, mission_id="m1")
            p2 = v.inspect(ws, mission_id="m1")
            self.assertTrue(validate_proof(p1, mission_id="m1", workspace_root=ws, verifier=v, reinspect=False)[0])
            rotate_key(key_path)
            v_after = TrustedWorkspaceVerifier(key_store_path=key_path, use_persisted_key=True)
            self.assertFalse(validate_proof(p1, mission_id="m1", workspace_root=ws, verifier=v_after, reinspect=False)[0])
            self.assertFalse(validate_proof(p2, mission_id="m1", workspace_root=ws, verifier=v_after, reinspect=False)[0])


@unittest.skipUnless(_dpapi_available(), "Windows DPAPI (win32crypt) required")
class Phase8A2RealDPAPIPersistenceTests(unittest.TestCase):
    """REAL (DPAPI/FS in temp environment): key protection, persistence across verifier restart, no secret leakage."""

    def test_dpapi_key_created_and_readable_and_not_plaintext(self):
        with tempfile.TemporaryDirectory() as td:
            key_path = Path(td) / "wk.dpapi"
            rec = create_key(key_path)
            self.assertTrue(key_file_exists(key_path))
            blob = key_path.read_bytes()
            # Should be DPAPI-protected blob, not plaintext JSON/key
            self.assertNotIn(b"key_b64", blob)
            self.assertNotIn(rec.key_bytes, blob)
            loaded = load_key(key_path)
            self.assertEqual(loaded.key_bytes, rec.key_bytes)
            self.assertEqual(loaded.key_id, rec.key_id)

    def test_proof_valid_after_verifier_restart_same_persisted_key(self):
        # "Redémarrage du vérificateur": new verifier instance loads same DPAPI-persisted key.
        with tempfile.TemporaryDirectory() as td:
            key_path = Path(td) / "wk.dpapi"
            ws = Path(td) / "ws"
            ws.mkdir()
            (ws / "state.txt").write_text("ok", encoding="utf-8")
            v1 = TrustedWorkspaceVerifier(key_store_path=key_path, use_persisted_key=True)
            proof = v1.inspect(ws, mission_id="mission-persist")
            ok1, issues1 = validate_proof(proof, mission_id="mission-persist", workspace_root=ws, verifier=v1, reinspect=True)
            self.assertTrue(ok1, issues1)
            del v1
            v2 = TrustedWorkspaceVerifier(key_store_path=key_path, use_persisted_key=True)  # restarted verifier
            ok2, issues2 = validate_proof(proof, mission_id="mission-persist", workspace_root=ws, verifier=v2, reinspect=True)
            self.assertTrue(ok2, issues2)

    def test_refusal_after_key_loss_or_change(self):
        with tempfile.TemporaryDirectory() as td:
            key_path = Path(td) / "wk.dpapi"
            ws = Path(td) / "ws"
            ws.mkdir()
            v1 = TrustedWorkspaceVerifier(key_store_path=key_path, use_persisted_key=True)
            proof = v1.inspect(ws, mission_id="m1")
            # Key loss: remove key file -> cannot verify persisted proof, new inspection required
            key_path.unlink()
            v_lost = TrustedWorkspaceVerifier(key_store_path=key_path, use_persisted_key=True)
            ok_lost, issues_lost = validate_proof(proof, mission_id="m1", workspace_root=ws, verifier=v_lost, reinspect=False)
            self.assertFalse(ok_lost)
            self.assertTrue("proof_signature_invalid" in issues_lost or "proof_verification_key_unavailable" in issues_lost)
            # Key change: create different key
            create_key(key_path)
            v_changed = TrustedWorkspaceVerifier(key_store_path=key_path, use_persisted_key=True)
            ok_changed, issues_changed = validate_proof(proof, mission_id="m1", workspace_root=ws, verifier=v_changed, reinspect=False)
            self.assertFalse(ok_changed)
            self.assertIn("proof_signature_invalid", issues_changed)

    def test_no_secret_in_proof_files_or_string_forms(self):
        with tempfile.TemporaryDirectory() as td:
            key_path = Path(td) / "wk.dpapi"
            ws = Path(td) / "ws"
            ws.mkdir()
            v = TrustedWorkspaceVerifier(key_store_path=key_path, use_persisted_key=True)
            proof = v.inspect(ws, mission_id="m1")
            rec = load_key(key_path)
            secret_b64 = __import__("base64").b64encode(rec.key_bytes).decode("ascii")
            proof_json = __import__("json").dumps(proof.to_dict(), ensure_ascii=False)
            # Key material must not appear in proof serialization/evidence/string representations
            self.assertNotIn(secret_b64, proof_json)
            self.assertNotIn(rec.key_bytes.hex(), proof_json)
            self.assertNotIn("signature_key", proof_json.lower())
            self.assertNotIn(secret_b64, str(proof.evidence))
            self.assertNotIn(secret_b64, repr(v))


if __name__ == "__main__":
    unittest.main()
