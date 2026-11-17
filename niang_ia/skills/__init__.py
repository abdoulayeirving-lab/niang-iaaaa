"""Curated, host-controlled Agent Skills for NIANG IA coding agents."""

from niang_ia.skills.catalog import (
    ALL_SKILL_IDS,
    ELITE_SKILL_IDS,
    VISUAL_SKILL_IDS,
    SkillDocument,
    SkillError,
    discover_skills,
    load_skill,
)
from niang_ia.skills.selector import SkillSelection, select_skills

__all__ = [
    "ALL_SKILL_IDS",
    "ELITE_SKILL_IDS",
    "VISUAL_SKILL_IDS",
    "SkillDocument",
    "SkillError",
    "SkillSelection",
    "discover_skills",
    "load_skill",
    "select_skills",
]
