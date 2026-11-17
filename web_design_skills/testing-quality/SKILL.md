---
name: testing-quality
description: Plan and run focused unit, integration, end-to-end, visual, accessibility, and regression tests with honest PASS, FAIL, or NOT TESTED evidence. Use for every code change and release-quality review.
---

# Testing and quality

## Identity and objective
Verify behavior through evidence at the smallest useful layer; code generation
alone is never a successful quality result.

## When to use / when not to use
Use for all implementation and maintenance work. Do not create tests that only
restate constants or implementation details, and do not claim a visual/runtime
check that was not run.

## Method
1. Identify changed behavior and the highest-risk failure modes.
2. Select the smallest focused tests, then broader tests if needed.
3. Test success, validation, errors, boundaries, and regressions.
4. Run build/type/lint checks appropriate to the repository.
5. Exercise the real UI/API path when the environment safely supports it.
6. Record each result with command, evidence, and `PASS`, `FAIL`, or
   `NOT TESTED`.

## Architecture and practices
- Prefer behavior-level assertions and deterministic fixtures.
- Isolate network, time, randomness, and filesystem effects when needed.
- Keep tests independent and clean up processes, ports, and temporary files.
- Never convert a failing test into a pass by disabling the assertion or
  weakening production validation.
- A green unit suite does not prove deployment, accessibility, or performance.

## Tools and technologies
Reuse the installed test runner: pytest/unittest, Jest/Vitest, Testing Library,
Playwright, Cypress, or the project-native equivalent. Consult each tool's
official docs before changing configuration.

## Execution instructions
Run targeted tests first. If a failure is unrelated, preserve it and report it
separately. Do not install packages or browsers without approval. Use disposable
data for integration tests.

## Quality example
A new API validation rule has a passing valid-input test and a failing
invalid-input test, plus a recorded runtime probe if an application server is
available.

## Common errors
- Treating compilation as proof that an endpoint or user flow works.
- Creating empty placeholder tests just to satisfy a package script.
- Ignoring test cleanup failures or flaky timing.
- Reporting skipped or unavailable checks as `PASS`.

## Premium Quality Gate
For web work, inspect design coherence, typography, responsive behavior,
accessibility, performance, SEO, functional controls, and truthful content.
For software, inspect architecture, security, error handling, tests,
performance, documentation, and maintainability. For each item record evidence
or `NOT TESTED`; any reproduced defect is `FAIL`. Overall `PASS` is permitted
only when every applicable required item has evidence and no failures remain.

## Validation criteria
Record actual test/build output and, for web work, capture evidence for
responsive layouts, accessibility, interactions, and performance on the
available target. Mark unavailable checks `NOT TESTED`; never infer them from
source inspection alone.

## Final checklist
- [ ] Focused tests cover introduced behavior and relevant regressions
- [ ] Build/type/lint outcomes are recorded
- [ ] Runtime/browser checks are distinguished from static checks
- [ ] Failures and unavailable checks are reported honestly
- [ ] Overall gate is not `PASS` while an applicable item is untested

## References
- [pytest](https://docs.pytest.org/)
- [Vitest](https://vitest.dev/guide/)
- [Testing Library](https://testing-library.com/docs/)
- [Playwright](https://playwright.dev/docs/intro)
- [Cypress](https://docs.cypress.io/)
- [W3C WCAG 2.2](https://www.w3.org/TR/WCAG22/)
