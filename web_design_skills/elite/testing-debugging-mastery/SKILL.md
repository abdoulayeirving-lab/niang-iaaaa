---
name: testing-debugging-mastery
description: Diagnose failures from evidence and build focused unit, integration, contract, and end-to-end tests that protect observable behavior. Use for debugging, regressions, flaky tests, and release validation.
---

# Testing and debugging mastery

## Objective and scope
Find the smallest reproducible cause, fix the behavior at its source, and
demonstrate the fix with a test that would fail before the change.

## When to use
Use for reported bugs, flaky behavior, new logic, regressions, and quality
gates. Do not weaken assertions, disable a failing test, or infer success from
compilation alone.

## Compatible technologies
Use the installed stack: pytest/unittest, Jest/Vitest, Testing Library,
Playwright/Cypress, JUnit, xUnit, Go testing, or the project-native runner.
Check the repository's versions and configuration first.

## Professional method
1. Capture the exact failure, environment, input, and expected behavior.
2. Reproduce with the smallest deterministic case; inspect logs and call paths.
3. Form a hypothesis and add or identify a failing regression test.
4. Fix the root cause with the smallest safe change.
5. Run the focused test, related suite, and relevant build/type/lint checks.
6. Repeat the original scenario and document any untested environment.

## Recommended test architecture
Keep unit tests fast and deterministic; isolate filesystem, network, clock, and
randomness. Use contract tests for boundaries, integration tests for real
collaborators, and E2E tests for critical user flows. Avoid asserting private
implementation details unless they are contractual.

## Code examples
Use parameterized tests to expose edge cases explicitly:

```python
import pytest


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("  Ada  ", "Ada"), ("", ""), ("  ", "")],
)
def test_normalize_display_name(raw: str, expected: str) -> None:
    assert normalize_display_name(raw) == expected
```

For asynchronous JavaScript, await the observable outcome:

```ts
it("shows a recoverable message when saving fails", async () => {
  saveProfile.mockRejectedValueOnce(new Error("offline"));
  render(<ProfileForm />);
  await user.click(screen.getByRole("button", { name: /save/i }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/try again/i);
});
```

## Best practices
- Assert public behavior, error shape, and important side effects.
- Keep fixtures minimal and test names descriptive.
- Record commands and pass/fail/skip counts.
- Treat flaky tests as defects; capture timing/state assumptions before changes.
- Keep test data isolated and clean up processes, ports, and temporary files.

## Anti-patterns
- Tests that only restate constants or duplicate implementation branches.
- Sleeps used instead of waiting for an observable condition.
- Catching an exception and asserting only that “something failed.”
- Marking a test skipped to make CI green without a reason and follow-up.
- Reporting skipped or unavailable checks as `PASS`.

## Error handling
Preserve the first useful traceback and logs, redact credentials and personal
data, and distinguish product failures from test-environment failures. Do not
silence cleanup, teardown, or fixture errors.

## Optimization
Profile slow suites before parallelizing. Use the smallest test layer that
proves the behavior, while retaining a focused integration test for critical
boundaries. Avoid shared mutable fixtures that create order dependence.

## Tests and validation
Run the new regression first, then its neighboring module, then the repository's
relevant suite. For web work, independently verify interactions, responsive
states, accessibility, and performance; mark missing browser/device checks
`NOT_TESTED`.

## Delivery checklist
- [ ] Failure is reproduced or the limitation is explicit
- [ ] Regression test fails before and passes after the fix
- [ ] Related tests/build/type/lint checks are reported
- [ ] Flakes, skips, cleanup, and environment limitations are addressed
- [ ] No test was weakened to force a pass

## Official documentation
- [pytest](https://docs.pytest.org/)
- [Vitest](https://vitest.dev/guide/)
- [Testing Library](https://testing-library.com/docs/)
- [Playwright](https://playwright.dev/docs/intro)
