---
name: clean-code-engineering
description: Improve code clarity, cohesion, typing, error handling, and maintainability in existing or new applications. Use for implementation, cleanup, and code-quality work across supported languages.
---

# Clean code engineering

## Objective and scope
Make the smallest correct change easy to understand, test, and safely extend.
This skill guides implementation quality; it does not authorize broad rewrites
or behavior changes hidden as cleanup.

## When to use
Use for feature work, bug fixes, code cleanup, or review findings involving
readability, duplication, typing, or complexity. Do not apply a style preference
that conflicts with established project conventions.

## Compatible technologies
Use the repository's existing language and tooling: Python, TypeScript/
JavaScript, Java, C#, Go, Rust, PHP, and their established linters and type
checkers. Inspect the project's version and configuration before choosing an
idiom.

## Professional method
1. Read the caller, callees, tests, and local conventions before editing.
2. State the observable behavior that must remain stable.
3. Make one cohesive change; separate unrelated formatting or refactoring.
4. Prefer names that expose domain intent and functions with one clear purpose.
5. Add types at public boundaries and where they prevent real ambiguity.
6. Validate with focused tests, then the narrowest applicable static checks.

## Recommended architecture
Keep domain decisions separate from I/O, UI, persistence, and provider SDKs.
Pass external dependencies through existing constructors or function
parameters when it improves testability. Avoid new layers for a single call
site; extract a helper when it has a clear name, reusable behavior, or focused
test.

## Code examples
Prefer explicit results and narrow responsibility:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class UserSummary:
    user_id: str
    display_name: str


def display_name(first: str, last: str) -> str:
    parts = (part.strip() for part in (first, last))
    return " ".join(part for part in parts if part)
```

In typed TypeScript, preserve the distinction between expected failure and
success instead of returning a fabricated value:

```ts
type Result<T> = { ok: true; value: T } | { ok: false; message: string };

function parsePort(value: string): Result<number> {
  const port = Number(value);
  return Number.isInteger(port) && port > 0 && port <= 65535
    ? { ok: true, value: port }
    : { ok: false, message: "Port must be an integer from 1 to 65535." };
}
```

## Best practices
- Preserve naming, formatting, dependency, and localization conventions.
- Keep functions short enough to follow without jumping across unrelated
  responsibilities; split by cohesive behavior, not arbitrary line counts.
- Prefer immutable values and explicit return types when they clarify contracts.
- Reuse a helper only when the abstraction has stable semantics.
- Remove duplication at its source, but do not over-generalize one-off code.

## Anti-patterns
- Boolean-flag functions that combine unrelated workflows.
- Deep nesting, unexplained abbreviations, and magic values.
- Catch-all exceptions that hide a failed operation or return success-shaped
  fallbacks.
- Type casts that suppress a fixable type error.
- Rewriting a module because a small local change looks less elegant.

## Error handling
Validate untrusted inputs at boundaries. Catch only errors the current layer
can recover from; otherwise preserve context and propagate explicitly. Include
actionable, non-sensitive messages. Never log tokens or silently replace a
failed dependency result with plausible data.

## Optimization
Optimize for comprehension first. Use a profiler, query plan, or benchmark
before changing algorithms or caching. Prefer the simplest data structure that
meets measured workload and memory limits.

## Tests and validation
Add a behavior-focused regression test for the changed contract. Exercise
success, invalid input, and relevant failure paths. Run the existing formatter,
linter, type checker, and focused tests where available; distinguish unrun
checks from passes.

## Delivery checklist
- [ ] Existing behavior and public contracts are preserved
- [ ] Responsibilities and names are clear
- [ ] Types and error paths are explicit
- [ ] No unnecessary abstraction or unrelated rewrite was added
- [ ] Focused tests and applicable static checks are recorded

## Official documentation
- [Python typing](https://docs.python.org/3/library/typing.html)
- [TypeScript handbook](https://www.typescriptlang.org/docs/handbook/intro.html)
- [Google developer documentation style](https://developers.google.com/style)
