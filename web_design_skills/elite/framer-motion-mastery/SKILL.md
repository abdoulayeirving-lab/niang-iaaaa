---
name: framer-motion-mastery
description: Build expressive React transitions, gestures, layout changes, and presence animations with Motion while respecting accessibility and component lifecycle. Use for React interaction and state-driven motion.
---

# Framer Motion / Motion mastery

## Objective and scope
Use Motion for state-driven React interactions, gestures, layout changes, and
enter/exit transitions. The current library is named Motion; use imports and
APIs matching the installed package and version.

## When to use
Use for React component transitions, drag/tap gestures, and layout animation.
Use CSS for simple decorative motion and GSAP for complex sequenced or
scroll-driven choreography. Do not stack Motion and GSAP on the same property
without separate responsibilities.

## Compatible technologies
React with the installed `motion` or legacy `framer-motion` package. Check
package manifests before choosing import paths. Use browser APIs only behind
React lifecycle-safe hooks.

## Professional method
1. Model the UI state and transition before choosing animation props.
2. Keep semantic content and focus behavior correct during presence changes.
3. Use variants for shared state and stable keys for list transitions.
4. Apply reduced-motion preferences to nonessential movement.
5. Keep gesture affordances accessible to keyboard users.
6. Test route changes, rapid toggling, unmount, and low-motion settings.

## Recommended architecture
Place motion behavior near the component whose state it represents. Share
variants only when states truly match; keep business logic independent of
animation. Avoid one global animation context for unrelated components.

## Code examples
Use Motion's reduced-motion hook for a state-driven transition:

```tsx
import { motion, useReducedMotion } from "motion/react";

function Notice({ open }: { open: boolean }) {
  const reduceMotion = useReducedMotion();
  return open ? (
    <motion.aside
      role="status"
      initial={reduceMotion ? false : { opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: reduceMotion ? 0 : 0.18 }}
    >
      Saved
    </motion.aside>
  ) : null;
}
```

## Best practices
- Keep animation duration and easing consistent in design tokens.
- Use `AnimatePresence` where exit transitions are meaningful.
- Respect reduced motion and do not animate essential feedback ambiguously.
- Preserve focus and reading order when content enters or leaves.
- Use `layout` only where layout interpolation adds clear user value.

## Anti-patterns
- Animating every element on page load with the same preset.
- Unstable list keys that recreate motion nodes on each render.
- Gesture-only actions unavailable through keyboard or buttons.
- Motion and GSAP both controlling one element's transform.
- Using animation to conceal slow or unresponsive application state.

## Error handling
Keep content accessible if animation is disabled or fails. Guard layout and
presence transitions against missing data; never make save/error feedback
dependent on animation completion.

## Optimization
Prefer transform/opacity, keep animated DOM small, and avoid repeated layout
measurement in large lists. Use Motion's supported reduced/render strategies
only after measuring bundle and runtime cost.

## Tests and validation
Test state changes, exit/unmount, reduced-motion behavior, focus order, keyboard
equivalence, and list key stability. Measure runtime/bundle impact when the
feature adds significant animation code.

## Delivery checklist
- [ ] Motion is used for React state/gesture needs
- [ ] Installed package and import path are verified
- [ ] Reduced motion and keyboard alternatives are implemented
- [ ] Presence and component cleanup are correct
- [ ] Animation libraries do not compete for the same element

## Official documentation
- [Motion documentation](https://motion.dev/docs/react)
- [React effects and lifecycle](https://react.dev/learn/synchronizing-with-effects)
- [MDN prefers-reduced-motion](https://developer.mozilla.org/docs/Web/CSS/@media/prefers-reduced-motion)
