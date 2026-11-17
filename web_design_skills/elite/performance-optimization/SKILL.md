---
name: performance-optimization
description: Measure and improve web vital metrics, rendering, bundle size, network delivery, memory, and interaction latency against real workload budgets. Use for slow pages, regressions, or performance targets.
---

# Performance optimization

## Objective and scope
Improve measured user-visible performance without sacrificing correctness,
accessibility, security, or maintainability.

## When to use
Use when a performance budget exists or profiling shows a regression. Do not
optimize based only on code appearance or a single noisy timing.

## Compatible technologies
Use browser DevTools, Lighthouse, Web Vitals, the project's bundler analyzer,
and language profilers already installed. Check device, browser, network, build
mode, and official metric definitions before comparing results.

## Professional method
1. Define the affected user flow, target devices, data, and metric.
2. Capture a baseline trace with warm/cold cache state documented.
3. Find the dominant cost (network, JS, rendering, server, or storage).
4. Make one narrow change and rerun the identical workload.
5. Check correctness, accessibility, memory, and variance.
6. Report numbers with environment and sample count; do not invent results.

## Recommended architecture
Load only the code and data required for the initial route; split optional
features at stable boundaries. Keep expensive computation off the main thread
when profiling supports it. Cache at explicit ownership boundaries with clear
invalidation.

## Code examples
Load noncritical browser code only when the user enters the feature:

```ts
async function openChart() {
  const { renderChart } = await import("./chart-view");
  renderChart(document.querySelector("#chart"));
}
```

## Best practices
- Use current Core Web Vitals definitions; optimize LCP, INP, and CLS with
  field/lab context in mind.
- Set image dimensions and responsive sources to prevent layout shift.
- Keep third-party scripts and fonts to the minimum needed.
- Paginate or virtualize only when data volume justifies it.
- Include CPU-throttled and constrained-network checks where possible.

## Anti-patterns
- Adding caches without freshness/ownership rules.
- Lazy-loading above-the-fold content or delaying essential interaction code.
- Optimizing a lab score while degrading a real user flow.
- Reporting one sample as a stable improvement.
- Removing security or accessibility checks to improve a benchmark.

## Error handling
Performance fallbacks must retain correct content and actions if an optional
chunk, image, worker, or API request fails. Provide retry or a lightweight
fallback for nonessential features; do not leave a blank viewport.

## Optimization
Use profiles to target the largest cost. Consider asset compression, route
splitting, fewer main-thread tasks, query efficiency, and measured caching.
Track memory and battery impact on mobile; cap animation and background work.

## Tests and validation
Compare baseline and post-change on identical device/browser/workload settings.
Check Core Web Vitals, long tasks, bundle changes, memory, and interaction
correctness. Mark unavailable field data or devices `NOT_TESTED`.

## Delivery checklist
- [ ] User-visible metric and baseline are documented
- [ ] Bottleneck is supported by a trace or profile
- [ ] Before/after measurements are comparable
- [ ] Correctness and accessibility remain intact
- [ ] Variance, device scope, and untested cases are reported

## Official documentation
- [web.dev Core Web Vitals](https://web.dev/articles/vitals)
- [web.dev performance](https://web.dev/learn/performance/)
- [Chrome DevTools Performance](https://developer.chrome.com/docs/devtools/performance/)
