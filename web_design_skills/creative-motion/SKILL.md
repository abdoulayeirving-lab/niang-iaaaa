---
name: creative-motion
description: Design purposeful, performant UI animation and interaction using CSS, GSAP, or Motion for React. Use for transitions, scroll-linked effects, micro-interactions, and animated web experiences.
---

# Creative motion

## Identity and objective
Use motion to clarify state, provide feedback, establish continuity, or support
the visual concept. Every animation must remain usable without motion.

## When to use / when not to use
Use when a task requests animation or when motion materially improves feedback.
Do not add motion to every element, use scroll effects that block reading, or
introduce a library without checking the existing stack.

## Method
1. Identify the user purpose and trigger for each animation.
2. Choose the simplest mechanism already supported by the project: CSS for
   small transitions, the installed animation library for coordinated state.
3. Specify duration, easing, distance, and interruption behavior consistently.
4. Animate transform/opacity where possible; avoid repeated layout and paint.
5. Respect `prefers-reduced-motion`; retain the same information and controls.
6. Test fast interactions, keyboard use, touch, and reduced-motion mode.

## Architecture and practices
- Keep animation state tied to component state and clean up listeners/timers.
- Avoid animating layout properties unless the design requires it and profiling
  supports the cost.
- Avoid perpetual motion, flashing, and large parallax movement.
- Ensure focus and click targets are stable while animation runs.
- In React Motion, use documented `motion.*` elements, valid object props, and
  the installed package's current API.

## Tools and technologies
Use CSS transitions/keyframes, [GSAP](https://gsap.com/docs/v3/), or
[Motion for React](https://motion.dev/docs/react) only when already available or
approved. Profile in browser developer tools.

## Execution instructions
Create a motion token set (short, standard, long; standard easing) and apply it
consistently. Implement reduced motion with a media query or the library's
documented reduced-motion support. Keep the nonanimated state complete.

## Quality example
A button gives a brief opacity/transform response on activation, retains a
visible focus ring, and has no movement in reduced-motion mode.

## Common errors
- Using unsupported component names or stringified object props.
- Starting animations off-screen without a visible reduced-motion alternative.
- Applying `will-change` permanently to many elements.
- Leaving observers, animation contexts, or timers active after unmount.

## Validation criteria
Check the documented browser support, reduced-motion behavior, keyboard and
touch interaction, no layout shift, and frame performance in the target
environment. Do not claim a frame-rate result without measuring it.

## Final checklist
- [ ] Each animation has a purpose and a clear trigger
- [ ] Reduced-motion mode preserves content and behavior
- [ ] Interactive controls remain stable and accessible
- [ ] Cleanup and performance were checked
- [ ] Package APIs match the installed version

## References
- [MDN CSS animations](https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_animations)
- [GSAP documentation](https://gsap.com/docs/v3/)
- [Motion for React](https://motion.dev/docs/react)
- [MDN `prefers-reduced-motion`](https://developer.mozilla.org/en-US/docs/Web/CSS/@media/prefers-reduced-motion)
