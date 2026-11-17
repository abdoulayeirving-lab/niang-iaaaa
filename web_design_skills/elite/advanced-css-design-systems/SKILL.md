---
name: advanced-css-design-systems
description: Create maintainable CSS foundations, design tokens, component states, responsive layouts, and lightweight motion without unnecessary frameworks. Use for design systems, visual consistency, and CSS architecture.
---

# Advanced CSS and design systems

## Objective and scope
Build a small, coherent styling system that makes product UI consistent,
responsive, accessible, and easy to change. Keep scope proportional to actual
reuse.

## When to use
Use for new visual foundations, token consolidation, component styling, or CSS
animation. Do not create a full design system for a one-off prototype unless
future reuse is explicit.

## Compatible technologies
Use browser-standard CSS, the project's preprocessor or CSS modules, and
existing utility/component conventions. Check browser support and build
configuration before adopting new CSS features.

## Professional method
1. Inventory existing tokens, selectors, component variants, and overrides.
2. Define semantic tokens for color, type, spacing, radius, elevation, and
   motion.
3. Set naming and layering conventions; migrate incrementally.
4. Build layouts with intrinsic sizing, Grid/Flexbox, and container queries
   where supported.
5. Add focus, hover, disabled, error, dark, and reduced-motion states.
6. Check computed styles, responsive behavior, and stylesheet size.

## Recommended architecture
Separate reset/base rules, tokens, layout primitives, components, and
feature-specific styles. Prefer CSS custom properties for runtime themes. Use
`:where()` and low-specificity selectors to keep overrides manageable.

## Code examples
Use semantic tokens and keep simple motion in CSS:

```css
:root {
  --color-accent: #5b3df5;
  --space-3: 0.75rem;
  --duration-fast: 160ms;
}

.button {
  transition: background-color var(--duration-fast) ease,
    transform var(--duration-fast) ease;
}

.button:hover {
  transform: translateY(-1px);
}

@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    scroll-behavior: auto !important;
    transition-duration: 0.01ms !important;
    animation-duration: 0.01ms !important;
  }
}
```

In production, scope reduced-motion rules to nonessential effects rather than
overriding application behavior indiscriminately.

## Best practices
- Name tokens by purpose (`--surface-raised`) rather than one screen's location.
- Keep contrast and states in the token system.
- Use logical properties for writing-mode and direction support.
- Prefer transforms/opacity for simple motion and preserve focus styles.
- Keep selectors readable and avoid dependence on DOM depth.

## Anti-patterns
- Unbounded `!important`, specificity wars, and duplicate token aliases.
- One global stylesheet that couples unrelated screens.
- Viewport-only breakpoints for components that should respond to container.
- CSS animations competing with Motion or GSAP on the same property.
- Automatically animating every property with `transition: all`.

## Error handling
Provide fallbacks for unsupported features and font/media loading failures.
Keep controls visible and usable if a theme variable or decorative stylesheet
fails. Avoid hiding elements based only on CSS when their state changes
semantically.

## Optimization
Remove dead CSS with the existing build pipeline, avoid expensive selectors on
large subtrees, and limit large blurred/filter layers. Use CSS for simple
effects rather than shipping a library; measure stylesheet and render cost.

## Tests and validation
Check tokens in light/dark states, focus/hover/error/disabled variants, reduced
motion, RTL where required, and narrow/wide containers. Run the existing
visual-regression or stylesheet checks if configured.

## Delivery checklist
- [ ] Tokens are semantic and fit existing conventions
- [ ] Component states and themes are complete
- [ ] Responsive and reduced-motion behavior is verified
- [ ] Specificity and duplicated styles remain controlled
- [ ] Library additions are justified by measured capability needs

## Official documentation
- [MDN CSS](https://developer.mozilla.org/docs/Web/CSS)
- [MDN custom properties](https://developer.mozilla.org/docs/Web/CSS/Using_CSS_custom_properties)
- [MDN prefers-reduced-motion](https://developer.mozilla.org/docs/Web/CSS/@media/prefers-reduced-motion)
