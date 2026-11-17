---
name: performance-engineering
description: Measure and improve CPU, memory, network, startup, rendering, and runtime performance using representative profiles and budgets. Use when a project has performance goals, regressions, or resource constraints.
---

# Performance engineering

## Identity and objective
Improve measured user-visible performance without reducing correctness,
accessibility, or security.

## When to use / when not to use
Use when performance is a stated goal or evidence shows a bottleneck. Do not
optimize by intuition, remove correctness checks, or claim a score without
running the measurement.

## Method
1. Define the user-visible metric, target device, workload, and baseline.
2. Capture a representative profile or trace before changing code.
3. Find the dominant cost and formulate one measurable hypothesis.
4. Make a narrow change and rerun the same workload.
5. Check memory/network behavior and correctness regressions.
6. Report environment, sample count, before/after, and remaining uncertainty.

## Architecture and practices
- Optimize the measured bottleneck, not a convenient proxy.
- Keep Core Web Vitals thresholds current and check the official definition.
- Bound caches and background work; avoid unbounded resource retention.
- Use lazy loading/code splitting only when it improves the measured path.
- Preserve reduced-motion and low-power behavior.

## Tools and technologies
Use browser performance tools, Lighthouse, Web Vitals, language profilers, and
system monitors already installed. See
[web.dev performance](https://web.dev/learn/performance/) and
[Core Web Vitals](https://web.dev/articles/vitals).

## Execution instructions
Use the same hardware, data, build mode, and steps for comparisons. Do not
install profilers or collect sensitive production data without approval.

## Quality example
A trace shows repeated image decoding blocks the main thread; a verified
responsive image change reduces the measured load cost while preserving visual
quality.

## Common errors
- Comparing different workloads or warm/cold cache states.
- Reporting one noisy timing as a stable improvement.
- Caching sensitive or stale data without invalidation.
- Optimizing a lab score while worsening the actual user flow.

## Validation criteria
Capture repeatable measurements, inspect variance, verify correctness and
accessibility, and test on representative constrained hardware when available.

## Final checklist
- [ ] Baseline and target workload are documented
- [ ] Bottleneck is evidenced by a profile or trace
- [ ] Before/after measurements are comparable
- [ ] Correctness, memory, and accessibility remain intact
- [ ] Untested devices and field performance are labelled

## References
- [web.dev performance](https://web.dev/learn/performance/)
- [Core Web Vitals](https://web.dev/articles/vitals)
- [Chrome DevTools Performance](https://developer.chrome.com/docs/devtools/performance/)
