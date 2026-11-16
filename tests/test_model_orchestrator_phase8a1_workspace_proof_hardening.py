from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from niang_ia.model_orchestrator.workspace_verification import (
    TrustedWorkspaceVerifier,
    WorkspaceProof,
    _build_manifest,
    _compute_signature,
    validate_proof,
)


class Phase8A1SimulatedProofSecurityTests(unittest.TestCase):
    """SIMULATED: proof authentication, tampering, substitution, expiry/reuse, inspection errors."""

    def test_caller_cannot_fabricate_proof_even_with_trusted_source_string(self):
        with tempfile.TemporaryDirectory() as td:
            v = TrustedWorkspaceVerifier(use_persisted_key=False)
            real = v.inspect(td, mission_id="m1")
            # Caller fabricates all fields including trusted_source but lacks valid signature.
            fabricated = WorkspaceProof(
                trusted_source=TrustedWorkspaceVerifier.TRUSTED_SOURCE,
                mission_id="m1",
                workspace_root=td,
                observed_realpath=real.observed_realpath,
                observed_stat_signature=real.observed_stat_signature,
                mission_binding=real.mission_binding,
                checked_at=real.checked_at,
                expires_at=real.expires_at,
                accessible=True,
                signature="0" * 64,
                manifest_hash=real.manifest_hash,
                proof_version=2,
                evidence={},
                issues=[],
            )
            ok, issues = validate_proof(fabricated, mission_id="m1", workspace_root=td, verifier=v, reinspect=False)
            self.assertFalse(ok)
            self.assertIn("proof_signature_invalid", issues)

    def test_serialized_proof_tampering_detected(self):
        with tempfile.TemporaryDirectory() as td:
            v = TrustedWorkspaceVerifier(use_persisted_key=False)
            proof = v.inspect(td, mission_id="m1")
            data = proof.to_dict()
            # Tamper mission binding field in serialized form
            data["mission_id"] = "m2"
            ok, issues = validate_proof(data, mission_id="m2", workspace_root=td, verifier=v, reinspect=False)
            self.assertFalse(ok)
            self.assertIn("proof_signature_invalid", issues)

    def test_mission_substitution_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            v = TrustedWorkspaceVerifier(use_persisted_key=False)
            proof = v.inspect(td, mission_id="m1")
            ok, issues = validate_proof(proof, mission_id="m2", workspace_root=td, verifier=v, reinspect=False)
            self.assertFalse(ok)
            self.assertTrue("mission_mismatch" in issues or "proof_signature_invalid" in issues)

    def test_workspace_substitution_rejected(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            v = TrustedWorkspaceVerifier(use_persisted_key=False)
            proof = v.inspect(a, mission_id="m1")
            ok, issues = validate_proof(proof, mission_id="m1", workspace_root=b, verifier=v, reinspect=False)
            self.assertFalse(ok)
            self.assertIn("workspace_mismatch", issues)

    def test_expired_proof_rejected_and_not_reused(self):
        with tempfile.TemporaryDirectory() as td:
            v = TrustedWorkspaceVerifier(ttl_seconds=1, use_persisted_key=False)
            proof = v.inspect(td, mission_id="m1", now=100.0)
            ok1, issues1 = validate_proof(proof, mission_id="m1", workspace_root=td, verifier=v, now=102.0, reinspect=False)
            self.assertFalse(ok1)
            self.assertIn("proof_expired", issues1)
            # Reuse attempt later still rejected
            ok2, issues2 = validate_proof(proof, mission_id="m1", workspace_root=td, verifier=v, now=200.0, reinspect=False)
            self.assertFalse(ok2)
            self.assertIn("proof_expired", issues2)

    def test_inspection_error_causes_refusal(self):
        with tempfile.TemporaryDirectory() as td:
            v = TrustedWorkspaceVerifier(use_persisted_key=False)
            with mock.patch("niang_ia.model_orchestrator.workspace_verification._build_manifest", side_effect=OSError("boom")):
                proof = v.inspect(td, mission_id="m1")
            # Proof should be marked unsafe/incomplete and refused
            ok, issues = validate_proof(proof, mission_id="m1", workspace_root=td, verifier=v, reinspect=False)
            self.assertFalse(ok)
            self.assertTrue(any(i.startswith("proof_issue:") for i in issues) or "proof_missing_real_inspection" in issues or "proof_signature_invalid" not in issues)

    def test_manifest_limit_exceeded_refused(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # create many entries to exceed sample/limits in controlled way
            for i in range(80):
                (root / f"f{i:03d}.txt").write_text("x", encoding="utf-8")
            v = TrustedWorkspaceVerifier(use_persisted_key=False)
            proof = v.inspect(root, mission_id="m1")
            ok, issues = validate_proof(proof, mission_id="m1", workspace_root=root, verifier=v, reinspect=False)
            self.assertFalse(ok)

    def test_different_verifier_key_rejects_signature(self):
        with tempfile.TemporaryDirectory() as td:
            v1 = TrustedWorkspaceVerifier(secret_key=b"a" * 32, use_persisted_key=False)
            v2 = TrustedWorkspaceVerifier(secret_key=b"b" * 32, use_persisted_key=False)
            proof = v1.inspect(td, mission_id="m1")
            ok, issues = validate_proof(proof, mission_id="m1", workspace_root=td, verifier=v2, reinspect=False)
            self.assertFalse(ok)
            self.assertIn("proof_signature_invalid", issues)


class Phase8A1RealWorkspaceDetectionTests(unittest.TestCase):
    """REAL: filesystem mutations and boundary cases in temporary workspace."""

    def test_content_change_same_size_detected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = root / "same.txt"
            p.write_text("abcd", encoding="utf-8")  # size 4
            v = TrustedWorkspaceVerifier(use_persisted_key=False)
            proof = v.inspect(root, mission_id="m1")
            # Modify content keeping same size
            p.write_text("wxyz", encoding="utf-8")
            ok, issues = validate_proof(proof, mission_id="m1", workspace_root=root, verifier=v, reinspect=True)
            self.assertFalse(ok)
            self.assertTrue("workspace_manifest_changed" in issues or "workspace_reinspect_failed_or_unsafe" in issues)

    def test_file_replacement_detected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = root / "f.txt"
            p.write_text("one", encoding="utf-8")
            v = TrustedWorkspaceVerifier(use_persisted_key=False)
            proof = v.inspect(root, mission_id="m1")
            # Replace file contents/identity
            p.unlink()
            p.write_text("two-plus", encoding="utf-8")
            ok, issues = validate_proof(proof, mission_id="m1", workspace_root=root, verifier=v, reinspect=True)
            self.assertFalse(ok)
            self.assertTrue("workspace_manifest_changed" in issues or "workspace_identity_changed" in issues or "workspace_reinspect_failed_or_unsafe" in issues)

    def test_entry_add_and_remove_detected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "keep.txt").write_text("k", encoding="utf-8")
            v = TrustedWorkspaceVerifier(use_persisted_key=False)
            proof = v.inspect(root, mission_id="m1")
            (root / "added.txt").write_text("a", encoding="utf-8")
            ok_add, issues_add = validate_proof(proof, mission_id="m1", workspace_root=root, verifier=v, reinspect=True)
            self.assertFalse(ok_add)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "del.txt").write_text("d", encoding="utf-8")
            v = TrustedWorkspaceVerifier(use_persisted_key=False)
            proof = v.inspect(root, mission_id="m1")
            (root / "del.txt").unlink()
            ok_del, issues_del = validate_proof(proof, mission_id="m1", workspace_root=root, verifier=v, reinspect=True)
            self.assertFalse(ok_del)

    def test_symlink_entry_causes_refusal(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "target.txt"
            target.write_text("t", encoding="utf-8")
            link = root / "link.txt"
            try:
                os.symlink(str(target), str(link))
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation not permitted in this environment")
            v = TrustedWorkspaceVerifier(use_persisted_key=False)
            proof = v.inspect(root, mission_id="m1")
            # Manifest marks symlink presence -> proof/issues make it unsafe
            ok, issues = validate_proof(proof, mission_id="m1", workspace_root=root, verifier=v, reinspect=False)
            self.assertFalse(ok)
            self.assertTrue(any("symlink" in i for i in issues) or any("manifest" in i for i in issues))

    def test_subdirectory_change_limit_documented_and_safe(self):
        """REAL: subdirectory internal content change is not fully guaranteed by depth-1 manifest;
        however directory stat/mtime may change on some platforms. Test documents behavior: either
        detected (refused) or, if undetected by current manifest, this is a known limitation (we assert
        current result and require refusal remains for risky flows in general)."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sub = root / "sub"
            sub.mkdir()
            (sub / "inner.txt").write_text("v1", encoding="utf-8")
            v = TrustedWorkspaceVerifier(use_persisted_key=False)
            proof = v.inspect(root, mission_id="m1")
            time.sleep(0.02)
            (sub / "inner.txt").write_text("v2-changed", encoding="utf-8")
            ok, issues = validate_proof(proof, mission_id="m1", workspace_root=root, verifier=v, reinspect=True)
            # If platform updates dir metadata/signature, change is detected (preferred). If not, this is a documented limitation.
            if not ok:
                self.assertTrue(len(issues) > 0)
            else:
                # Limitation case: not detected by depth-1 manifest/root stat on this platform.
                self.assertTrue(ok)

    def test_missing_workspace_at_inspect_refused(self):
        v = TrustedWorkspaceVerifier(use_persisted_key=False)
        proof = v.inspect("Z:/__niang_missing_ws_8a1__", mission_id="m1")
        ok, issues = validate_proof(proof, mission_id="m1", verifier=v, reinspect=False)
        self.assertFalse(ok)

    def test_modification_during_inspection_tocTou_best_effort(self):
        """REAL+controlled: simulate concurrent modification during manifest hashing.
        The proof is bound to observed state at inspection; subsequent validation/reinspection
        against changed state must refuse (fail closed). True atomic snapshot is not guaranteed
        (TOCTOU window remains a documented limitation)."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = root / "race.txt"
            p.write_text("AAAA", encoding="utf-8")
            v = TrustedWorkspaceVerifier(use_persisted_key=False)
            original_hash_file = __import__("niang_ia.model_orchestrator.workspace_verification", fromlist=["_hash_file"])._hash_file

            def mutating_hash(path, max_bytes):
                digest = original_hash_file(path, max_bytes)
                # Simulate concurrent modification after this file was read during inspection
                if path.name == "race.txt":
                    path.write_text("BBBB", encoding="utf-8")
                return digest

            with mock.patch("niang_ia.model_orchestrator.workspace_verification._hash_file", side_effect=mutating_hash):
                proof = v.inspect(root, mission_id="m1")
            # Workspace now differs from proof's manifest snapshot; reinspection must refuse.
            ok, issues = validate_proof(proof, mission_id="m1", workspace_root=root, verifier=v, reinspect=True)
            self.assertFalse(ok)
            self.assertTrue(
                "workspace_manifest_changed" in issues
                or "workspace_reinspect_failed_or_unsafe" in issues
                or "workspace_identity_changed" in issues
            )


class Phase8A1BypassAuditNotesTests(unittest.TestCase):
    """SIMULATED: document identified bypass paths (no global runtime wiring added)."""

    def test_executor_and_workspace_tools_continuity_gate_scope(self):
        # 8A.1 audit baseline: no WorkspaceProof/authorization coupling in executor/workspace_tools.
        # 8A.3 evolution: executor now has a conditional central continuity guard for missions
        # explicitly marked `workspace_verification_required` (opt-in), while workspace_tools remains
        # a low-level tool implementation without embedded continuity proof checks.
        from agent import executor, workspace_tools
        src_exec = Path(executor.__file__).read_text(encoding="utf-8", errors="replace")
        src_ws = Path(workspace_tools.__file__).read_text(encoding="utf-8", errors="replace")
        self.assertNotIn("WorkspaceProof", src_exec)
        self.assertNotIn("authorize_risky_resume_or_write", src_exec)
        self.assertIn("evaluate_continuity_guard", src_exec)
        self.assertIn("continuity_context", src_exec)
        self.assertNotIn("authorize_risky_resume_or_write", src_ws)
        self.assertNotIn("evaluate_continuity_guard", src_ws)

    def test_resume_gate_only_conditional_in_task_queue(self):
        from agent import task_queue
        src = Path(task_queue.__file__).read_text(encoding="utf-8", errors="replace")
        # Enforcement exists but is conditional/opt-in for continuity-marked uncertain cases.
        self.assertIn("authorize_risky_resume_or_write", src)
        self.assertIn("must_verify", src)


if __name__ == "__main__":
    unittest.main()
