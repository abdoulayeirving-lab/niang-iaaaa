from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


LEGACY_SKILL_IDS = (
    "premium-web-design",
    "advanced-ui-ux",
    "creative-motion",
    "immersive-3d-web",
    "responsive-mobile-first",
    "ecommerce-conversion",
    "fullstack-engineering",
    "frontend-mastery",
    "backend-engineering",
    "database-architecture",
    "api-integrations",
    "software-architecture",
    "ai-engineering",
    "desktop-engineering",
    "mobile-engineering",
    "game-engineering",
    "security-engineering",
    "testing-quality",
    "performance-engineering",
    "devops-deployment",
)
ELITE_SKILL_IDS = (
    "clean-code-engineering",
    "software-architecture",
    "senior-fullstack-engineering",
    "testing-debugging-mastery",
    "secure-software-engineering",
    "awwwards-level-web-design",
    "gsap-animation-mastery",
    "framer-motion-mastery",
    "threejs-webgl-mastery",
    "advanced-ui-ux-responsive",
    "performance-optimization",
    "advanced-css-design-systems",
    "backend-api-engineering",
    "devops-production-engineering",
    "code-review-refactoring",
)
_ELITE_ADDITIONAL_SKILL_IDS = tuple(
    skill_id for skill_id in ELITE_SKILL_IDS if skill_id != "software-architecture"
)
ALL_SKILL_IDS = tuple(dict.fromkeys((*LEGACY_SKILL_IDS, *ELITE_SKILL_IDS)))
DEFAULT_SKILL_ROOT = Path(__file__).resolve().parents[2] / "web_design_skills"
ELITE_SKILL_ROOT = DEFAULT_SKILL_ROOT / "elite"
MAX_SKILL_BYTES = 100_000
_SKILL_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SKILL_DIRECTORIES = {
    **{skill_id: Path(skill_id) for skill_id in LEGACY_SKILL_IDS},
    **{
        skill_id: Path("elite") / skill_id
        for skill_id in _ELITE_ADDITIONAL_SKILL_IDS
    },
}


class SkillError(ValueError):
    """A skill is missing, invalid, or outside the curated library."""


@dataclass(frozen=True)
class SkillDocument:
    id: str
    name: str
    description: str
    instructions: str
    source: Path


def discover_skills(
    root: str | Path = DEFAULT_SKILL_ROOT,
    *,
    require_all: bool = True,
) -> dict[str, SkillDocument]:
    library = _resolve_library_root(root)
    active_directories = [
        path for path in library.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    ]
    folded: dict[str, str] = {}
    for path in active_directories:
        key = path.name.casefold()
        if key in folded:
            raise SkillError(
                f"Duplicate skill directory names differ only by case: "
                f"{folded[key]} and {path.name}."
            )
        folded[key] = path.name
        if path.name not in LEGACY_SKILL_IDS and path.name != "elite":
            raise SkillError(f"Unregistered skill directory: {path.name}.")

    elite_directory = library / "elite"
    if _is_link_or_junction(elite_directory):
        raise SkillError("The elite skill directory cannot be a symbolic link or junction.")
    if elite_directory.is_dir():
        for path in elite_directory.iterdir():
            if not path.is_dir():
                continue
            if path.name not in _ELITE_ADDITIONAL_SKILL_IDS:
                raise SkillError(f"Unregistered elite skill directory: {path.name}.")
            if _is_link_or_junction(path):
                raise SkillError(f"Elite skill paths cannot be links: {path.name}.")

    discovered: dict[str, SkillDocument] = {}
    for skill_id in ALL_SKILL_IDS:
        relative_directory = _SKILL_DIRECTORIES.get(skill_id, Path("software-architecture"))
        skill_file = library / relative_directory / "SKILL.md"
        if skill_file.is_file():
            discovered[skill_id] = load_skill(skill_id, root=library)
    missing = [skill_id for skill_id in ALL_SKILL_IDS if skill_id not in discovered]
    if require_all and missing:
        raise SkillError(f"Missing registered skills: {', '.join(missing)}.")
    return discovered


def load_skill(
    skill_id: str,
    *,
    root: str | Path = DEFAULT_SKILL_ROOT,
) -> SkillDocument:
    if (
        not isinstance(skill_id, str)
        or not _SKILL_ID_PATTERN.fullmatch(skill_id)
        or skill_id not in ALL_SKILL_IDS
    ):
        raise SkillError(f"Skill ID is not allowed: {skill_id!r}.")

    library = _resolve_library_root(root)
    relative_directory = _SKILL_DIRECTORIES.get(skill_id, Path("software-architecture"))
    directory = library / relative_directory
    skill_file = directory / "SKILL.md"
    directory_chain = [library.joinpath(*relative_directory.parts[:index])
                       for index in range(1, len(relative_directory.parts) + 1)]
    if any(_is_link_or_junction(path) for path in (*directory_chain, skill_file)):
        raise SkillError(f"Skill paths cannot be links: {skill_id}.")
    try:
        resolved_directory = directory.resolve(strict=True)
        resolved_file = skill_file.resolve(strict=True)
        resolved_directory.relative_to(library)
        resolved_file.relative_to(resolved_directory)
        if not resolved_file.is_file():
            raise SkillError(f"Invalid skill path: {skill_id}.")
        if resolved_file.stat().st_size > MAX_SKILL_BYTES:
            raise SkillError(f"Skill file exceeds the size limit: {skill_id}.")
        text = resolved_file.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise SkillError(f"Missing skill file: {skill_id}/SKILL.md.") from exc
    except UnicodeDecodeError as exc:
        raise SkillError(f"Skill file is not valid UTF-8: {skill_id}.") from exc
    except OSError as exc:
        raise SkillError(f"Skill file could not be read: {skill_id}.") from exc
    except ValueError as exc:
        raise SkillError(f"Skill path escapes the library: {skill_id}.") from exc

    metadata, instructions = _parse_frontmatter(text, skill_id)
    name = metadata.get("name", "")
    description = metadata.get("description", "")
    if name != skill_id:
        raise SkillError(
            f"Skill name must match its directory ({skill_id!r}), not {name!r}."
        )
    if not description or len(description) > 1024:
        raise SkillError(
            f"Skill description must contain 1 to 1024 characters: {skill_id}."
        )
    if not instructions:
        raise SkillError(f"Skill instructions are empty: {skill_id}.")
    return SkillDocument(
        id=skill_id,
        name=name,
        description=description,
        instructions=instructions,
        source=resolved_file,
    )


def _resolve_library_root(root: str | Path) -> Path:
    candidate = Path(root).expanduser()
    if _is_link_or_junction(candidate):
        raise SkillError("The skill library root cannot be a symbolic link or junction.")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise SkillError(f"The skill library cannot be opened: {candidate}.") from exc
    if not resolved.is_dir():
        raise SkillError("The skill library root must be a directory.")
    return resolved


def _is_link_or_junction(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or (is_junction is not None and is_junction())


def _parse_frontmatter(text: str, skill_id: str) -> tuple[Mapping[str, str], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SkillError(f"Skill {skill_id} is missing YAML frontmatter.")
    try:
        end = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration as exc:
        raise SkillError(f"Skill {skill_id} has unterminated YAML frontmatter.") from exc

    metadata: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip():
            continue
        key, separator, raw_value = line.partition(":")
        if not separator or key not in {"name", "description", "license", "compatibility"}:
            raise SkillError(f"Skill {skill_id} has unsupported frontmatter.")
        if key in metadata:
            raise SkillError(f"Skill {skill_id} repeats frontmatter field {key}.")
        metadata[key] = _parse_scalar(raw_value.strip(), skill_id)

    body = "\n".join(lines[end + 1:]).strip()
    return metadata, body


def _parse_scalar(value: str, skill_id: str) -> str:
    if not value:
        return ""
    if value.startswith('"'):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise SkillError(f"Skill {skill_id} has invalid quoted frontmatter.") from exc
        if not isinstance(parsed, str):
            raise SkillError(f"Skill {skill_id} frontmatter values must be strings.")
        return parsed
    if value.startswith("'"):
        if len(value) < 2 or not value.endswith("'"):
            raise SkillError(f"Skill {skill_id} has invalid quoted frontmatter.")
        return value[1:-1].replace("''", "'")
    return value
