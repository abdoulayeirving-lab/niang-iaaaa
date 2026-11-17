---
name: gsap-animation-mastery
description: Build coordinated GSAP timelines, scroll-linked sequences, and high-control web motion with cleanup, reduced-motion support, and mobile performance budgets. Use for complex choreographed animation or scroll narratives.
---

# GSAP animation mastery

## Objective and scope
Use GSAP where precise timelines, sequencing, scrubbing, or complex cross-element
coordination materially improves a web experience. It is not the default for
simple hover, opacity, or layout transitions.

## When to use
Use for multi-step timelines, pinned/scroll narratives, synchronized scenes, or
imperative animation across many targets. Prefer CSS for simple decorative
effects and Motion for React component/gesture transitions; do not combine
libraries for the same property without a documented reason.

## Compatible technologies
Use the installed GSAP version and documented plugins. For React, follow the
current `@gsap/react` guidance and the repository's build/bundling setup.
Verify plugin licensing and registration requirements before use.

## Professional method
1. Define the narrative, trigger, duration, and expected mobile behavior.
2. Identify animated properties and ensure layout remains meaningful without
   motion.
3. Create one scoped timeline; use labels and relative positions for
   synchronization.
4. Add reduced-motion behavior and touch/short-viewport alternatives.
5. Revert contexts and kill triggers on unmount or route change.
6. Profile frame time on representative mobile hardware.

## Recommended architecture
Keep timeline construction in a component hook or feature controller, scoped to
owned elements. Avoid global selectors and global timelines. Separate
scroll-trigger setup from content rendering and use one scroll owner per scene.

## Code examples
React setup with scoped cleanup and a reduced-motion branch:

```tsx
import { useRef } from "react";
import { gsap } from "gsap";
import { useGSAP } from "@gsap/react";

function Intro() {
  const root = useRef<HTMLElement>(null);
  useGSAP(() => {
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduceMotion) return;
    gsap.timeline()
      .from("[data-title]", { y: 24, opacity: 0, duration: 0.45 })
      .from("[data-copy]", { y: 12, opacity: 0, duration: 0.3 }, "-=0.15");
  }, { scope: root });
  return <section ref={root}><h1 data-title>Welcome</h1><p data-copy>Details</p></section>;
}
```

## Best practices
- Animate `transform` and `opacity` for most transitions; measure other
  properties.
- Use timeline labels to express semantic synchronization.
- Respect `prefers-reduced-motion` and preserve content visibility.
- Bound ScrollTrigger counts and avoid pinning essential navigation.
- Use context cleanup for React and explicit `kill()` for owned imperative work.

## Anti-patterns
- Competing scroll listeners or timelines writing the same property.
- Animating layout-heavy properties on every frame without profiling.
- Creating timelines during every render or leaving triggers after unmount.
- Scroll hijacking, forced autoplay, or motion that causes nausea.
- Adding GSAP alongside Motion for a trivial fade.

## Error handling
Guard optional DOM targets and route-dependent content. Handle missing plugin
registration explicitly in development; do not swallow timeline setup errors.
If animation setup fails, leave semantic content visible and functional.

## Optimization
Prefer one timeline per coherent scene, use `will-change` only briefly and
selectively, avoid oversized blurred layers, and test reduced-motion and
low-power paths. Profile before introducing frame callbacks.

## Tests and validation
Verify the timeline's terminal state, cleanup on unmount, route transitions,
reduced motion, scroll/touch behavior, and mobile frame stability. Distinguish
automated timeline assertions from actual device profiling.

## Delivery checklist
- [ ] GSAP is justified by timeline/scroll complexity
- [ ] Timeline ownership and cleanup are explicit
- [ ] Reduced motion and touch behavior work
- [ ] No conflicting animation library writes the same properties
- [ ] Performance is measured on representative devices

## Official documentation
- [GSAP documentation](https://gsap.com/docs/v3/)
- [GSAP React](https://gsap.com/resources/React/)
- [MDN prefers-reduced-motion](https://developer.mozilla.org/docs/Web/CSS/@media/prefers-reduced-motion)
