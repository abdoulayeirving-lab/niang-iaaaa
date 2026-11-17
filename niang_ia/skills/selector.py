from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable

from agent import workspace_tools
from niang_ia.skills.catalog import (
    DEFAULT_SKILL_ROOT,
    SkillDocument,
    SkillError,
    discover_skills,
)


_BASE_SKILLS = (
    "clean-code-engineering",
    "testing-debugging-mastery",
    "secure-software-engineering",
)
_ELITE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("software-architecture", (
        "software architecture", "architecture", "architectural decision",
        "system design", "refactor architecture",
    )),
    ("senior-fullstack-engineering", (
        "full stack", "full-stack", "fullstack", "from scratch",
        "application complete", "application complète", "de a a z",
    )),
    ("testing-debugging-mastery", (
        "test", "tests", "testing", "debug", "debugging", "bug",
        "regression", "flaky",
    )),
    ("secure-software-engineering", (
        "security", "secure", "sécurité", "securite", "auth",
        "authentication", "authentification", "authorization", "autorisation",
        "payment", "paiement", "secret", "owasp",
    )),
    ("awwwards-level-web-design", (
        "premium web", "premium website", "site premium", "site web premium",
        "awwwards", "portfolio", "landing page", "brand site", "website",
        "site web", "site internet",
    )),
    ("gsap-animation-mastery", (
        "gsap", "scrolltrigger", "scroll animation", "scroll-linked",
        "scroll linked", "timeline animation", "complex timeline",
        "parallax timeline",
    )),
    ("framer-motion-mastery", (
        "framer motion", "motion for react", "react animation",
        "react transition", "gesture animation", "route transition",
    )),
    ("threejs-webgl-mastery", (
        "3d", "three.js", "threejs", "webgl", "react three fiber",
        "r3f", "3d viewer", "3d scene",
    )),
    ("advanced-ui-ux-responsive", (
        "ui/ux", "ui ux", "ux", "responsive", "mobile-first", "interface",
        "dashboard", "form", "user flow", "parcours utilisateur",
        "accessibility", "accessibilité",
    )),
    ("performance-optimization", (
        "performance", "lighthouse", "core web vitals", "optimize",
        "optimization", "slow", "latency", "vitesse", "optimisation",
        "optimiser",
    )),
    ("advanced-css-design-systems", (
        "css", "design system", "design token", "component styling",
        "css animation", "hover effect", "style guide",
    )),
    ("backend-api-engineering", (
        "backend", "back-end", "rest api", "rest", "api", "endpoint",
        "server", "serveur", "fastapi", "django", "express", "nestjs",
        "spring", "asp.net", "webhook", "graphql",
    )),
    ("devops-production-engineering", (
        "devops", "deployment", "deploy", "production", "ci/cd",
        "pipeline", "docker", "kubernetes", "observability", "rollback",
    )),
    ("code-review-refactoring", (
        "code review", "review code", "review pull request", "review pr",
        "refactor", "refactoring", "cleanup", "clean up",
    )),
)
_LEGACY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ai-engineering", (
        "artificial intelligence", "intelligence artificielle", "llm", "rag",
        "embedding", "agent ia", "agent ai", "local model", "modèle local",
    )),
    ("desktop-engineering", (
        "desktop", "application de bureau", "tkinter", "pyside", "pyqt",
        "electron", "tauri", "windows application",
    )),
    ("mobile-engineering", (
        "mobile app", "application mobile", "app mobile", "android", "ios",
        "flutter", "react native", "iphone app",
    )),
    ("game-engineering", (
        "video game", "jeu vidéo", "jeu video", "unity", "unreal", "godot",
        "gameplay",
    )),
    ("database-architecture", (
        "database", "base de données", "base de donnees", "postgres",
        "sqlite", "mysql", "mongodb", "schema migration", "data model",
    )),
    ("ecommerce-conversion", (
        "e-commerce", "ecommerce", "online store", "boutique", "panier",
        "checkout", "commerce", "catalogue produit",
    )),
    ("api-integrations", (
        "external api", "api integration", "intégration api",
        "integration api", "oauth", "external webhook", "websocket",
    )),
)
_DEPENDENCIES = {
    "awwwards-level-web-design": (
        "advanced-ui-ux-responsive",
        "advanced-css-design-systems",
        "performance-optimization",
    ),
    "backend-api-engineering": ("senior-fullstack-engineering", "software-architecture"),
    "code-review-refactoring": (),
}
_ANIMATION_WORDS = (
    "animation", "animations", "animate", "animated", "animé", "animée", "motion",
)
_COMPLEX_MOTION_WORDS = (
    "scroll", "timeline", "parallax", "choreograph", "synchronized", "scrub",
)
_SIMPLE_MOTION_WORDS = (
    "simple", "hover", "fade", "microinteraction", "micro-interaction",
)
_WEB_WORDS = (
    "website", "web", "site web", "site internet", "landing page", "react",
    "vue", "angular", "next.js", "nextjs",
)
_MAX_SKILLS = 10


@dataclass(frozen=True)
class SkillSelection:
    skills: tuple[SkillDocument, ...]
    reasons: dict[str, tuple[str, ...]]

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(skill.id for skill in self.skills)


def select_skills(
    goal: str,
    workspace_root: str | Path | None = None,
    *,
    catalog_root: str | Path = DEFAULT_SKILL_ROOT,
    max_skills: int = _MAX_SKILLS,
) -> SkillSelection:
    if not isinstance(goal, str) or not goal.strip():
        raise SkillError("A non-empty goal is required to select skills.")
    if (
        isinstance(max_skills, bool)
        or not isinstance(max_skills, int)
        or not 1 <= max_skills <= _MAX_SKILLS
    ):
        raise SkillError(f"Skill selection limit must be between 1 and {_MAX_SKILLS}.")

    catalog = discover_skills(catalog_root, require_all=True)
    normalized_goal = _normalize(goal)
    reasons: dict[str, list[str]] = {
        skill_id: ["elite baseline requirement"]
        for skill_id in _BASE_SKILLS
    }
    for skill_id, triggers in (*_ELITE_RULES, *_LEGACY_RULES):
        matches = [
            trigger for trigger in triggers
            if _matches_trigger(normalized_goal, _normalize(trigger))
        ]
        if matches:
            reasons.setdefault(skill_id, []).extend(matches)

    if workspace_root is not None:
        project = workspace_tools.detect_project_languages(workspace_root)
        languages = set(project.get("languages", []))
        frameworks = set(project.get("frameworks", []))
        if languages.intersection({"javascript", "typescript", "jsx", "tsx", "html", "css"}) or frameworks.intersection({"nextjs", "vite", "typescript"}):
            reasons.setdefault("advanced-ui-ux-responsive", []).append(
                "detected frontend project"
            )
        if languages.intersection({"java", "kotlin", "go", "csharp"}) and _contains_any(
            normalized_goal, ("api", "backend", "serveur", "service")
        ):
            reasons.setdefault("backend-api-engineering", []).append(
                "detected backend project"
            )
        if "react" in frameworks and _contains_any(normalized_goal, _ANIMATION_WORDS):
            reasons.setdefault("framer-motion-mastery", []).append(
                "React project with requested animation"
            )

    _add_animation_choices(normalized_goal, reasons)
    for skill_id in tuple(reasons):
        for dependency in _DEPENDENCIES.get(skill_id, ()):
            reasons.setdefault(dependency, []).append(f"complements {skill_id}")

    ordered_ids = [
        skill_id
        for skill_id, _ in (*_ELITE_RULES, *_LEGACY_RULES)
        if skill_id in reasons and skill_id not in _BASE_SKILLS
    ]
    selected_ids = list(dict.fromkeys((*_BASE_SKILLS, *ordered_ids)))
    if len(selected_ids) > max_skills:
        selected_ids = _limit_selection(selected_ids, reasons, max_skills)
    missing = [skill_id for skill_id in selected_ids if skill_id not in catalog]
    if missing:
        raise SkillError(f"Selected skills are missing: {', '.join(missing)}.")
    return SkillSelection(
        skills=tuple(catalog[skill_id] for skill_id in selected_ids),
        reasons={skill_id: tuple(reasons[skill_id]) for skill_id in selected_ids},
    )


def _add_animation_choices(
    goal: str,
    reasons: dict[str, list[str]],
) -> None:
    has_web_context = _contains_any(goal, _WEB_WORDS) or "awwwards-level-web-design" in reasons
    if not has_web_context or not _contains_any(goal, _ANIMATION_WORDS):
        return
    if _contains_any(goal, ("gsap", "scrolltrigger", "scroll animation", "timeline")):
        reasons.setdefault("gsap-animation-mastery", []).append(
            "explicit GSAP or complex timeline requirement"
        )
        return
    if _contains_any(goal, ("framer motion", "motion for react")):
        reasons.setdefault("framer-motion-mastery", []).append(
            "explicit React Motion requirement"
        )
        return
    if _contains_any(goal, _SIMPLE_MOTION_WORDS):
        reasons.setdefault("advanced-css-design-systems", []).append(
            "simple effect suited to CSS"
        )
        return
    if _contains_any(goal, _COMPLEX_MOTION_WORDS):
        reasons.setdefault("gsap-animation-mastery", []).append(
            "complex scroll or timeline choreography"
        )
        return
    reasons.setdefault("gsap-animation-mastery", []).append(
        "animation option for non-React or coordinated sequences"
    )
    reasons.setdefault("framer-motion-mastery", []).append(
        "animation option for React state and interactions"
    )


def _limit_selection(
    selected_ids: Iterable[str],
    reasons: dict[str, list[str]],
    max_skills: int,
) -> list[str]:
    ids = list(selected_ids)
    baseline = [skill_id for skill_id in _BASE_SKILLS if skill_id in ids]
    direct = [
        skill_id for skill_id in ids
        if not all(reason.startswith("complements ") for reason in reasons[skill_id])
        and skill_id not in baseline
    ]
    complementary = [
        skill_id for skill_id in ids
        if skill_id not in baseline and skill_id not in direct
    ]
    return (baseline + direct + complementary)[:max_skills]


def _contains_any(text: str, values: tuple[str, ...]) -> bool:
    return any(_matches_trigger(text, _normalize(value)) for value in values)


def _matches_trigger(text: str, trigger: str) -> bool:
    if not trigger:
        return False
    return re.search(rf"(?<!\w){re.escape(trigger)}(?!\w)", text) is not None


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return " ".join(
        "".join(character for character in decomposed if not unicodedata.combining(character)).split()
    )
