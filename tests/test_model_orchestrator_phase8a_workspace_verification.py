from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

from niang_ia.model_orchestrator.continuity import (
    assess_resume_safety,
    build_handoff_context,
)
from niang_ia.model_orchestrator.workspace_verification import (
    TrustedWorkspaceVerifier,
    WorkspaceProof,
    authorize_risky_resume_or_write,
    validate_proof,
)


class Phase8ASimulatedWorkspaceVerificationTests(unittest.TestCase):
    """SIMULATED: logic/guard behavior using controlled or synthetic inputs."""

    def _proof(self, verifier, mission_id, ws, **kwargs):
        return verifier.inspect(ws, mission_id=mission_id, **kwargs)

    def test_missing_proof_refused(self):
        handoff = build_handoff_context(mission_id="m", objective="o")
        ok, issues = assess_resume_safety(handoff, require_trusted_proof=True, proof=None, mission_id="m")
        self.assertFalse(ok)
        self.assertTrue(any("proof" in i or "trusted" in i for i in issues))

    def test_forged_or_untrusted_proof_refused(self):
        with tempfile.TemporaryDirectory() as td:
            verifier = TrustedWorkspaceVerifier(use_persisted_key=False)
            real = verifier.inspect(td, mission_id="m1")
            # Forged: caller-constructed proof without valid verifier signature/authentication.
            forged = WorkspaceProof(
                trusted_source=TrustedWorkspaceVerifier.TRUSTED_SOURCE,
                mission_id=real.mission_id,
                workspace_root=real.workspace_root,
                observed_realpath=real.observed_realpath,
                observed_stat_signature=real.observed_stat_signature,
                mission_binding=real.mission_binding,
                checked_at=real.checked_at,
                expires_at=real.expires_at,
                accessible=True,
                evidence={},
                issues=[],
            )
            ok, issues = validate_proof(forged, mission_id="m1", workspace_root=td, verifier=verifier, reinspect=False)
            self.assertFalse(ok)
            self.assertTrue(
                "proof_signature_invalid" in issues or "proof_missing_real_inspection" in issues or "untrusted_proof_source" in issues
            )

    def test_proof_for_other_workspace_refused(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            verifier = TrustedWorkspaceVerifier(use_persisted_key=False)
            proof_a = verifier.inspect(a, mission_id="m1")
            ok, issues = validate_proof(proof_a, mission_id="m1", workspace_root=b, reinspect=False)
            self.assertFalse(ok)
            self.assertIn("workspace_mismatch", issues)

    def test_stale_proof_refused(self):
        with tempfile.TemporaryDirectory() as td:
            verifier = TrustedWorkspaceVerifier(ttl_seconds=1, use_persisted_key=False)
            proof = verifier.inspect(td, mission_id="m1", now=1000.0)
            ok, issues = validate_proof(proof, mission_id="m1", workspace_root=td, now=1005.0, reinspect=False)
            self.assertFalse(ok)
            self.assertIn("proof_expired", issues)

    def test_inaccessible_workspace_refused(self):
        verifier = TrustedWorkspaceVerifier(use_persisted_key=False)
        proof = verifier.inspect("Z:/__niang_missing_workspace__unlikely__", mission_id="m1")
        self.assertFalse(proof.accessible)
        ok, issues = validate_proof(proof, mission_id="m1", reinspect=False)
        self.assertFalse(ok)

    def test_mission_mismatch_refused(self):
        with tempfile.TemporaryDirectory() as td:
            verifier = TrustedWorkspaceVerifier(use_persisted_key=False)
            proof = verifier.inspect(td, mission_id="m1")
            ok, issues = validate_proof(proof, mission_id="m2", workspace_root=td, reinspect=False)
            self.assertFalse(ok)
            self.assertIn("mission_mismatch", issues)

    def test_uncertain_write_requires_refusal_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            verifier = TrustedWorkspaceVerifier(use_persisted_key=False)
            proof = verifier.inspect(td, mission_id="m1")
            handoff = build_handoff_context(
                mission_id="m1", objective="o",
                actions_completed=[{"id": "w1", "status": "unknown", "side_effects_possible": True}],
            )
            ok, issues = authorize_risky_resume_or_write(
                mission_id="m1", workspace_root=td, proof=proof, handoff=handoff,
                current_step_state="unknown_unverified",
            )
            self.assertFalse(ok)
            self.assertTrue(any("uncertain" in i or "not_verified" in i or "state_not_verified" in i for i in issues))

    def test_potential_double_write_blocked_when_previous_uncertain(self):
        # Simulated: previous write outcome uncertain => checkpoint not replayable and gate refuses risky resume/write.
        handoff = build_handoff_context(
            mission_id="m1", objective="o",
            actions_completed=[{"id": "write1", "status": "in_progress", "side_effects_possible": True}],
        )
        for cp in handoff.checkpoints:
            self.assertFalse(cp.replay_allowed)
        with tempfile.TemporaryDirectory() as td:
            verifier = TrustedWorkspaceVerifier(use_persisted_key=False)
            proof = verifier.inspect(td, mission_id="m1")
            ok, issues = authorize_risky_resume_or_write(
                mission_id="m1", workspace_root=td, proof=proof, handoff=handoff, current_step_state="in_progress",
            )
            self.assertFalse(ok)

    def test_resume_after_failure_scenario_requires_verified_state(self):
        # Simulated failure/interruption: unknown state refused even with valid proof until caller declares verified step state.
        with tempfile.TemporaryDirectory() as td:
            verifier = TrustedWorkspaceVerifier(use_persisted_key=False)
            proof = verifier.inspect(td, mission_id="m1")
            ok, _ = authorize_risky_resume_or_write(
                mission_id="m1", workspace_root=td, proof=proof, handoff=None, current_step_state="unknown",
            )
            self.assertFalse(ok)
            ok2, issues2 = authorize_risky_resume_or_write(
                mission_id="m1", workspace_root=td, proof=proof, handoff=None, current_step_state="completed", verifier=verifier,
            )
            self.assertTrue(ok2, issues2)

    def test_approvals_preserved_in_handoff(self):
        handoff = build_handoff_context(
            mission_id="m1", objective="o", approvals_state={"tool_x": "approved", "scope": "once"}
        )
        self.assertEqual(handoff.approvals_state["tool_x"], "approved")
        self.assertEqual(handoff.approvals_state["scope"], "once")

    def test_bool_string_alone_not_sufficient_in_trusted_mode(self):
        handoff = build_handoff_context(mission_id="m1", objective="o")
        ok, issues = assess_resume_safety(
            handoff, workspace_verified=True, verification_evidence="looks ok",
            require_trusted_proof=True, mission_id="m1", workspace_root=None, proof=None,
        )
        self.assertFalse(ok)


class Phase8ARealWorkspaceInspectionTests(unittest.TestCase):
    """REAL: actual filesystem inspection in controlled temporary workspace."""

    def test_real_inspection_produces_evidence_from_filesystem(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.txt").write_text("hello", encoding="utf-8")
            (root / "sub").mkdir()
            verifier = TrustedWorkspaceVerifier(use_persisted_key=False)
            proof = verifier.inspect(root, mission_id="mission-real")
            self.assertTrue(proof.accessible)
            self.assertEqual(proof.observed_realpath, str(root.resolve()))
            self.assertTrue(proof.observed_stat_signature)
            self.assertEqual(proof.trusted_source, TrustedWorkspaceVerifier.TRUSTED_SOURCE)
            names = {e.get("name") for e in proof.evidence.get("entries_sample", [])}
            self.assertIn("a.txt", names)
            self.assertIn("sub", names)
            ok, issues = validate_proof(proof, mission_id="mission-real", workspace_root=root, verifier=verifier)
            self.assertTrue(ok, issues)

    def test_real_workspace_identity_change_detected_on_reinspect(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "f.txt").write_text("x", encoding="utf-8")
            verifier = TrustedWorkspaceVerifier(use_persisted_key=False)
            proof = verifier.inspect(root, mission_id="m1")
            # Real mutation (entry add): manifest/signature consistency must detect change.
            time.sleep(0.02)
            (root / "new.txt").write_text("y", encoding="utf-8")
            ok, issues = validate_proof(proof, mission_id="m1", workspace_root=root, verifier=verifier, reinspect=True)
            self.assertFalse(ok)
            self.assertTrue(
                "workspace_manifest_changed" in issues
                or "workspace_identity_changed" in issues
                or "workspace_reinspect_failed_or_unsafe" in issues
            )

    def test_real_missing_workspace_detected(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "gone"
            target.mkdir()
            verifier = TrustedWorkspaceVerifier(use_persisted_key=False)
            proof = verifier.inspect(target, mission_id="m1")
            target.rmdir()
            ok, issues = validate_proof(proof, mission_id="m1", workspace_root=target, verifier=verifier, reinspect=True)
            self.assertFalse(ok)
            self.assertTrue(any("missing" in i or "inaccessible" in i for i in issues))

    def test_real_mission_marker_binding(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".mission").write_text("mission-real", encoding="utf-8")
            verifier = TrustedWorkspaceVerifier(use_persisted_key=False)
            proof = verifier.inspect(
                root, mission_id="mission-real",
                expected_mission_markers={"mission_marker_file": ".mission", "mission_marker_content": "mission-real"},
            )
            ok, issues = validate_proof(proof, mission_id="mission-real", workspace_root=root, verifier=verifier)
            self.assertTrue(ok, issues)
            bad = verifier.inspect(
                root, mission_id="mission-real",
                expected_mission_markers={"mission_marker_file": ".mission", "mission_marker_content": "other"},
            )
            ok2, issues2 = validate_proof(bad, mission_id="mission-real", workspace_root=root, verifier=verifier, reinspect=False)
            self.assertFalse(ok2)
            self.assertTrue(any("mission_marker_mismatch" in i for i in issues2))


if __name__ == "__main__":
    unittest.main()
