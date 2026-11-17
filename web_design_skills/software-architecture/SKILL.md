---
name: software-architecture
description: Make maintainable software design and refactoring decisions using clear boundaries, SOLID principles, and evidence from the existing codebase. Use for architecture changes, complex features, and cross-module refactoring.
---

# Software architecture

## Identity and objective
Reduce change risk and improve clarity while fitting the system that actually
exists, rather than imposing a fashionable architecture.

## Objective and scope
Design cohesive modules and stable contracts that meet the application's
functional and operational constraints. This skill complements
`senior-fullstack-engineering`; it is not permission for an unrequested rewrite.

## When to use / when not to use
Use for cross-cutting changes, new modules, refactoring, dependency boundaries,
or design trade-offs. Do not introduce layers, services, or patterns without a
concrete requirement.

## Compatible technologies
Use the project's existing language, runtime, module system, and architecture
tools. Consult version-specific language and platform documentation before
recommending APIs or framework patterns.

## Method
1. Map current modules, dependencies, entry points, and the behavior to
   preserve.
2. State constraints and quality attributes: security, latency, availability,
   changeability, and operational limits.
3. Compare the smallest viable designs and document consequential trade-offs.
4. Keep domain rules independent of transport/storage details where it helps
   testability.
5. Refactor in behavior-preserving steps with focused tests.
6. Review dependency direction and remove abstractions that have no real
   variation or reuse.

## Recommended architecture
- Apply SOLID as a diagnostic, not as a requirement to create one class per
  concept.
- Prefer explicit module boundaries, cohesive responsibilities, and narrow
  interfaces.
- Keep side effects at clear boundaries and inject external dependencies when
  tests need control.
- Use domain language already established by the project.
- Record decisions when they constrain future work.

## Best practices
- Compare viable options against real quality attributes and operating limits.
- Keep design decisions traceable to requirements or observed constraints.
- Prefer incremental changes that preserve behavior and public contracts.

## Code examples
Use a narrow typed port to keep domain behavior independent of storage details:

```python
from typing import Protocol


class UserStore(Protocol):
    def find_name(self, user_id: str) -> str | None: ...


def greeting(user_id: str, users: UserStore) -> str:
    name = users.find_name(user_id)
    if name is None:
        raise LookupError("User was not found.")
    return f"Hello, {name}"
```

Add a boundary only when the project has meaningful variation or testability
benefits; do not create an interface for every class.

## Tools and technologies
Use the existing language and module system. Diagrams and architecture records
are optional; keep them proportional to the change. Consult the
[Microsoft Architecture Center](https://learn.microsoft.com/azure/architecture/)
for system-level trade-offs and the relevant language documentation for
language-specific behavior.

## Execution instructions
Before refactoring, identify behavior to preserve and establish the smallest
relevant test baseline. Change one boundary at a time; do not combine an
unrelated cleanup with the requested design change.

## Quality example
A service boundary owns its domain rule, exposes a narrow typed interface, and
has a test that verifies behavior without requiring a live database.

## Anti-patterns
- Applying Clean Architecture mechanically to a small script.
- Introducing generic factories or registries without multiple concrete
  consumers.
- Changing behavior while labeling a patch a refactor.
- Hiding dependency failures behind success-shaped defaults.

## Error handling
Keep failures explicit at service and infrastructure boundaries. Translate
errors only where the current layer can add useful domain context; preserve
causes and never return success-shaped defaults for failed dependencies.

## Optimization
Optimize for changeability and measured runtime constraints. Profile before
splitting services or introducing caches; account for operational cost,
latency, ownership, and failure modes in any proposed distribution.

## Validation criteria
Review dependency direction, public interfaces, testability, migration cost,
error behavior, and whether the simplest design was chosen.

## Final checklist
- [ ] Architecture decisions respond to observed constraints
- [ ] Existing behavior and public contracts are preserved
- [ ] Boundaries are cohesive and dependencies point intentionally
- [ ] Abstractions are justified by real use
- [ ] Tests cover the behavior changed by refactoring

## References
- [Microsoft Azure Architecture Center](https://learn.microsoft.com/azure/architecture/)
- [Martin Fowler's architecture articles](https://martinfowler.com/architecture/)
