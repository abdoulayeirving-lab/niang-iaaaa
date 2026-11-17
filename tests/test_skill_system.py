import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from niang_ia.skills.catalog import (
    ALL_SKILL_IDS,
    ELITE_SKILL_IDS,
    SkillError,
    discover_skills,
    load_skill,
)
from niang_ia.skills.selector import select_skills
from niang_ia.skills.quality_gate import evaluate_quality_gate, format_quality_gate


class SkillCatalogTests(unittest.TestCase):
    def test_discovers_the_complete_portable_skill_library(self):
        catalog = discover_skills()
        self.assertEqual(set(catalog), set(ALL_SKILL_IDS))
        self.assertEqual(len(ELITE_SKILL_IDS), 15)
        for skill_id, skill in catalog.items():
            self.assertEqual(skill.name, skill_id)
            self.assertTrue(skill.description)
            self.assertTrue(skill.instructions)
        for skill_id in ELITE_SKILL_IDS:
            skill = catalog[skill_id]
            for section in (
                "## Objective and scope",
                "## When to use",
                "## Compatible technologies",
                "## Code examples",
                "## Best practices",
                "## Anti-patterns",
                "## Error handling",
                "## Optimization",
            ):
                self.assertIn(section, skill.instructions, skill_id)
            self.assertTrue(
                "## Method" in skill.instructions or "## Professional method" in skill.instructions,
                skill_id,
            )
            self.assertTrue(
                "## Architecture and practices" in skill.instructions
                or "## Recommended architecture" in skill.instructions
                or "## Recommended test architecture" in skill.instructions,
                skill_id,
            )
            self.assertTrue(
                "## Validation criteria" in skill.instructions
                or "## Tests and validation" in skill.instructions,
                skill_id,
            )
            self.assertTrue(
                "## Final checklist" in skill.instructions
                or "## Delivery checklist" in skill.instructions,
                skill_id,
            )
            self.assertTrue(
                "## References" in skill.instructions
                or "## Official documentation" in skill.instructions,
                skill_id,
            )
            self.assertRegex(skill.instructions, r"https://[^\s)]+")
            self.assertRegex(skill.instructions, r"```[a-zA-Z0-9+#.-]*\n")

    def test_existing_architecture_skill_was_snapshotted_before_enrichment(self):
        snapshot = (
            Path(__file__).resolve().parents[1]
            / "web_design_skills"
            / ".legacy"
            / "software-architecture-SKILL.md"
        )
        if not snapshot.is_file():
            self.skipTest("Legacy source snapshots are excluded from release packages.")
        self.assertTrue(snapshot.is_file())
        self.assertIn("SOLID principles", snapshot.read_text(encoding="utf-8"))
        self.assertIn("## Code examples", discover_skills()["software-architecture"].instructions)

    def test_rejects_malformed_skill_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            skill_dir = Path(directory) / "premium-web-design"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                "# Missing frontmatter\nInstructions\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(SkillError, "frontmatter"):
                load_skill("premium-web-design", root=Path(directory))

    def test_reports_a_missing_selected_skill_instead_of_silently_skipping_it(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(SkillError, "premium-web-design"):
                load_skill("premium-web-design", root=Path(directory))

    def test_rejects_noncanonical_skill_ids(self):
        with self.assertRaisesRegex(SkillError, "not allowed"):
            load_skill("../premium-web-design")

    def test_selects_complementary_skills_for_premium_animated_3d_shop(self):
        selected = select_skills(
            "Créer un site web premium responsive, animé en 3D, avec une boutique et paiement.",
        )
        ids = set(selected.ids)
        self.assertTrue({
            "awwwards-level-web-design",
            "advanced-ui-ux-responsive",
            "gsap-animation-mastery",
            "framer-motion-mastery",
            "threejs-webgl-mastery",
            "ecommerce-conversion",
            "clean-code-engineering",
            "testing-debugging-mastery",
            "secure-software-engineering",
        }.issubset(ids))
        self.assertLessEqual(len(ids), 10)

    def test_selects_elite_web_skills_without_assuming_three_d(self):
        selected = select_skills("Créer un site web premium animé et responsive.")
        ids = set(selected.ids)
        self.assertTrue({
            "awwwards-level-web-design",
            "advanced-ui-ux-responsive",
            "clean-code-engineering",
            "gsap-animation-mastery",
            "framer-motion-mastery",
            "performance-optimization",
            "testing-debugging-mastery",
            "secure-software-engineering",
        }.issubset(ids))
        self.assertNotIn("threejs-webgl-mastery", ids)
        self.assertLessEqual(len(ids), 10)

    def test_selects_threejs_only_when_the_mission_requires_three_d(self):
        ordinary = set(select_skills("Create a polished responsive web page.").ids)
        immersive = set(select_skills("Create an interactive Three.js product viewer in 3D.").ids)
        self.assertNotIn("threejs-webgl-mastery", ordinary)
        self.assertIn("threejs-webgl-mastery", immersive)

    def test_selects_the_elite_backend_combination(self):
        selected = set(select_skills("Build a secure backend REST API with validation and tests.").ids)
        self.assertTrue({
            "senior-fullstack-engineering",
            "software-architecture",
            "backend-api-engineering",
            "clean-code-engineering",
            "secure-software-engineering",
            "testing-debugging-mastery",
        }.issubset(selected))

    def test_selects_visual_asset_skill_for_visual_web_missions_with_complementary_skills(self):
        selected = select_skills(
            "Create a luxury car dealership landing page with genuine photography and responsive images."
        )
        ids = set(selected.ids)
        self.assertIn("visual-asset-intelligence", ids)
        self.assertTrue({
            "awwwards-level-web-design",
            "advanced-ui-ux-responsive",
            "performance-optimization",
        }.issubset(ids))
        self.assertLessEqual(len(ids), 10)

    def test_does_not_add_web_design_skills_for_non_web_visual_assets(self):
        ids = set(select_skills("Create original sprites and textures for a Godot game.").ids)
        self.assertIn("visual-asset-intelligence", ids)
        self.assertNotIn("awwwards-level-web-design", ids)

    def test_chooses_motion_framework_from_explicit_technology_without_loading_both(self):
        gsap = set(select_skills("Build a GSAP scroll timeline for this site.").ids)
        motion = set(select_skills("Implement Framer Motion React route transitions.").ids)
        self.assertIn("gsap-animation-mastery", gsap)
        self.assertNotIn("framer-motion-mastery", gsap)
        self.assertIn("framer-motion-mastery", motion)
        self.assertNotIn("gsap-animation-mastery", motion)

    def test_prefers_css_for_simple_web_animation(self):
        ids = set(select_skills("Add a simple CSS hover animation to this website.").ids)
        self.assertIn("advanced-css-design-systems", ids)
        self.assertNotIn("gsap-animation-mastery", ids)
        self.assertNotIn("framer-motion-mastery", ids)
        self.assertNotIn("threejs-webgl-mastery", ids)

    def test_does_not_select_unrelated_web_skills_for_desktop_api_mission(self):
        selected = select_skills(
            "Créer une application desktop Tkinter avec une API FastAPI et une base SQLite.",
        )
        ids = set(selected.ids)
        self.assertIn("desktop-engineering", ids)
        self.assertIn("backend-api-engineering", ids)
        self.assertIn("database-architecture", ids)
        self.assertNotIn("threejs-webgl-mastery", ids)
        self.assertNotIn("ecommerce-conversion", ids)

    def test_selection_reasons_are_available_for_audit(self):
        selected = select_skills("Créer une application mobile Flutter avec authentification.")
        self.assertTrue(selected.reasons["mobile-engineering"])
        self.assertTrue(selected.reasons["secure-software-engineering"])

    def test_quality_gate_requires_evidence_for_every_applicable_web_dimension(self):
        complete = [
            {"name": name, "status": "PASS", "evidence": f"verified {name}"}
            for name in (
                "npm-test", "npm-build", "security", "visual_design",
                "responsive", "accessibility", "interactions", "performance",
            )
        ]
        report = evaluate_quality_gate(
            "Build a premium website",
            complete,
            selected_skill_ids=("premium-web-design",),
        )
        self.assertEqual(report["status"], "PASS")

        incomplete = evaluate_quality_gate(
            "Build a premium website",
            complete[:-1],
            selected_skill_ids=("premium-web-design",),
        )
        self.assertEqual(incomplete["status"], "NOT_TESTED")
        self.assertIn("NON TESTÉ", format_quality_gate(incomplete))

    def test_quality_gate_surfaces_failed_checks_instead_of_masking_them(self):
        report = evaluate_quality_gate(
            "Create an API",
            [
                {"name": "npm-test", "status": "FAIL", "evidence": "npm-test"},
                {"name": "npm-build", "status": "PASS", "evidence": "npm-build"},
            ],
        )
        self.assertEqual(report["status"], "FAIL")

    def test_visual_asset_gate_requires_real_verification_and_visual_review(self):
        unverified = evaluate_quality_gate(
            "Create a website with real images.",
            [],
            selected_skill_ids=("visual-asset-intelligence",),
        )
        checks = {item["id"]: item["status"] for item in unverified["checks"]}
        self.assertEqual(checks["visual_assets"], "NOT_TESTED")
        self.assertEqual(checks["visual_asset_review"], "NOT_TESTED")

        verified = evaluate_quality_gate(
            "Create a website with real images.",
            [
                {
                    "name": "visual-assets-integrity",
                    "status": "PASS",
                    "evidence": "Assets, provenance, references and credits verified.",
                },
                {
                    "name": "visual_asset_review",
                    "status": "NOT_TESTED",
                    "evidence": "Composition and semantic fit were not visually reviewed.",
                },
            ],
            selected_skill_ids=("visual-asset-intelligence",),
        )
        checks = {item["id"]: item["status"] for item in verified["checks"]}
        self.assertEqual(checks["visual_assets"], "PASS")
        self.assertEqual(checks["visual_asset_review"], "NOT_TESTED")
        self.assertNotEqual(verified["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
