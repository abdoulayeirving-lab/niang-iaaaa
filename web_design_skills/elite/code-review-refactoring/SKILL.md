---
name: code-review-refactoring
description: Review changes for concrete correctness, security, compatibility, and maintainability risks, then refactor behavior-preservingly with focused tests. Use for pull-request review, code cleanup, and legacy simplification.
---

# Code review and refactoring

## Objective and scope
Find actionable defects and reduce complexity without changing intended
behavior. Review findings should cite evidence and impact; refactors should be
small, reversible, and protected by tests.

## When to use
Use for a requested code review, refactor, or repeated complexity/duplication.
Do not invent defects from style preferences, rewrite unrelated modules, or
silently alter public behavior.

## Compatible technologies
Use the project's diff tools, tests, linters, type checkers, language server,
and static analyzers. Apply conventions for its installed language/runtime.

## Professional method
1. Read the full diff and relevant callers, tests, config, and data boundaries.
2. Trace changed paths for correctness, security, concurrency, and compatibility.
3. Report findings by severity with file/line evidence, consequence, and
   condition required to reproduce.
4. Separate confirmed defects from questions and optional improvements.
5. For refactoring, establish behavior tests and make one structural change at
   a time.
6. Re-run focused tests and compare observable behavior.

## Recommended architecture
Preserve module boundaries unless evidence shows they are the source of the
problem. Extract cohesive functions or types behind stable contracts. Avoid
changing architecture and business behavior in the same patch.

## Code examples
Replace duplicated validation with a named helper while preserving the same
accepted range:

```ts
function isValidPort(value: number): boolean {
  return Number.isInteger(value) && value >= 1 && value <= 65535;
}

if (!isValidPort(config.port)) {
  throw new Error("Port must be an integer from 1 to 65535.");
}
```

Before refactoring, confirm the prior contract through tests or call sites;
similar-looking checks may intentionally differ.

## Best practices
- Lead with the highest-impact confirmed finding.
- Check failure paths, boundary values, ownership checks, and resource cleanup.
- Keep comments for non-obvious intent, not line-by-line narration.
- Use before/after tests to distinguish cleanup from behavior change.
- Explain uncertainty when dependencies or runtime conditions are unavailable.

## Anti-patterns
- Nitpicks presented as security or correctness bugs.
- Broad catch blocks, relaxed validation, or changed outputs to make tests pass.
- Reformatting unrelated files in a review fix.
- “Refactor” without evidence of preserved behavior.
- Findings without impact, path, or actionable remediation.

## Error handling
Preserve diagnostic context and report failing commands accurately. Do not
claim a test passed if it was skipped, mocked, or unavailable. If refactoring
uncovers an unrelated failure, leave it unchanged and identify it separately.

## Optimization
Reduce cognitive complexity and unnecessary dependencies before micro-tuning.
For performance concerns, require a profile or repeatable measurement. Keep
diff size focused so reviewers can verify it.

## Tests and validation
Add a regression test for each fixed defect. Run relevant unit/integration
tests, type/lint checks, and diff review. Verify public contracts and migration
effects; report residual risks and unrun checks.

## Delivery checklist
- [ ] Findings cite concrete evidence and impact
- [ ] No style-only preference is reported as a defect
- [ ] Refactor preserves tested behavior
- [ ] Focused regression tests and static checks pass
- [ ] Unrelated issues and untested assumptions are separated

## Official documentation
- [Google Engineering Practices: Code Review](https://google.github.io/eng-practices/review/)
- [GitHub code review](https://docs.github.com/pull-requests/collaborating-with-pull-requests/reviewing-changes-in-pull-requests)
- [Martin Fowler: Refactoring](https://martinfowler.com/books/refactoring.html)
