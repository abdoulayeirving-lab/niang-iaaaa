from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from typing import TypeVar


_Result = TypeVar("_Result")
_WEB_PROJECT_TERMS = (
    "landing page",
    "landingpage",
    "site web",
    "site internet",
    "site vitrine",
    "website",
    "web site",
    "webpage",
    "web page",
    "page web",
    "web app",
    "frontend",
    "front end",
)


def is_web_frontend_request(goal: str) -> bool:
    if not isinstance(goal, str) or not goal.strip():
        return False
    normalized = unicodedata.normalize("NFKD", goal.casefold())
    normalized = "".join(
        character for character in normalized
        if not unicodedata.combining(character)
    )
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized).strip()
    return any(
        f" {term} " in f" {normalized} "
        for term in _WEB_PROJECT_TERMS
    )


def dispatch_project_creation(
    description: str,
    project_name: str,
    *,
    web_handler: Callable[[str], _Result],
    default_handler: Callable[[], _Result],
) -> _Result:
    if not is_web_frontend_request(description):
        return default_handler()

    goal = description.strip()
    if isinstance(project_name, str) and project_name.strip():
        goal += f"\n\nRequested project name: {project_name.strip()}"
    return web_handler(goal)
