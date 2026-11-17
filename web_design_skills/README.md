# NIANG IA development skills

This directory is the curated, read-only-by-default source for 34 portable
Agent Skills used by NIANG IA: the existing 20 general skills and a 15-skill
elite engineering profile. `software-architecture` is shared by both sets.
Elite additions live under `elite/<skill-id>/SKILL.md`; existing direct
directories remain unchanged, and `.legacy/` preserves prior drafts and the
pre-enrichment architecture skill.

NIANG IA selects at most 10 complementary skills for each mission. The elite
profile is preferred for software engineering; existing AI, desktop, mobile,
game, database, and commerce skills remain selectable for their domains. Cline
receives only selected skills through its host-mediated loader, which rechecks
every requested ID. OpenCode uses this source and mission-specific permissions
that allow only selected skill IDs. Neither integration grants general
filesystem access through skill loading.

The mission quality gate reports `PASS`, `FAIL`, or `NOT_TESTED` (`NON TESTÉ`).
It counts only checks actually run by the host; applicable design, responsive,
accessibility, interaction, performance, and security dimensions remain
`NOT_TESTED` unless there is recorded evidence. `PASS` requires evidence for
every applicable dimension.

Mission output also distinguishes selected skills from IDs actually reported
as loaded.

The library catalog and task selector live in `niang_ia/skills/`. The
`quality_gate.py` evaluator adds its report to Cline/OpenCode mission results.

Use the official references linked by each skill and verify the installed
framework version before using version-specific commands or APIs.

## Elite engineering profile

The profile contains the 15 IDs requested for professional engineering:

`clean-code-engineering`, `software-architecture`,
`senior-fullstack-engineering`, `testing-debugging-mastery`,
`secure-software-engineering`, `awwwards-level-web-design`,
`gsap-animation-mastery`, `framer-motion-mastery`,
`threejs-webgl-mastery`, `advanced-ui-ux-responsive`,
`performance-optimization`, `advanced-css-design-systems`,
`backend-api-engineering`, `devops-production-engineering`,
`code-review-refactoring`.

For motion, the selector uses explicit technology/task cues; it does not
silently install or apply every library. CSS is preferred for simple effects,
Motion for React state and gestures, GSAP for complex timelines/scroll scenes,
and Three.js only for a real 3D requirement. When both GSAP and Motion are
selected as options, the skill instructions require a justified division of
responsibility and prohibit both controlling the same effect.

## Canonical skills

Web: `premium-web-design`, `advanced-ui-ux`, `creative-motion`,
`immersive-3d-web`, `responsive-mobile-first`, `ecommerce-conversion`.

Engineering: `fullstack-engineering`, `frontend-mastery`,
`backend-engineering`, `database-architecture`, `api-integrations`,
`software-architecture`.

Advanced technology: `ai-engineering`, `desktop-engineering`,
`mobile-engineering`, `game-engineering`.

Production quality: `security-engineering`, `testing-quality`,
`performance-engineering`, `devops-deployment`.
