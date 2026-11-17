---
name: advanced-ui-ux-responsive
description: Design and implement accessible, responsive product interfaces from user goals through interaction states and mobile layouts. Use for dashboards, forms, navigation, and responsive redesigns.
---

# Advanced UI/UX and responsive design

## Objective and scope
Make the primary user task understandable and achievable across viewport sizes,
input methods, and assistive technologies.

## When to use
Use for application screens, dashboards, forms, navigation, and responsive
flows. Do not redesign a whole product when the requirement is a small
behavioral fix.

## Compatible technologies
Use semantic HTML, modern CSS (Grid, Flexbox, container queries), and the
existing React/Vue/Angular or native component system. Follow the established
design tokens and accessibility test setup.

## Professional method
1. Identify user roles, goal, success state, and likely failure points.
2. Map information hierarchy and the interaction states: idle, focus, loading,
   success, empty, error, disabled.
3. Define content reflow and navigation at narrow and wide viewports.
4. Implement semantics and keyboard behavior before decorative styling.
5. Validate zoom/text scaling, touch targets, contrast, focus, and screen reader
   labels.

## Recommended architecture
Separate shared design tokens, reusable controls, page composition, and
feature-specific state. Use native HTML controls when suitable. Keep responsive
rules close to the component and avoid duplicating variants across pages.

## Code examples
Use a content-first layout that reflows without device-specific hacks:

```css
.form-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(16rem, 0.7fr);
  gap: clamp(1rem, 4vw, 3rem);
}

@media (max-width: 48rem) {
  .form-layout {
    grid-template-columns: 1fr;
  }
}
```

## Best practices
- Use real labels, fieldsets, headings, buttons, and links.
- Keep focus visible and keyboard order aligned with visual order.
- Reflow content at zoom and narrow widths; do not rely on fixed pixel canvases.
- Explain errors beside the affected control and associate them programmatically.
- Use touch targets and spacing suited to fingers without removing keyboard use.

## Anti-patterns
- Placeholder text used as the only form label.
- Hover-only controls, focus traps, and controls without accessible names.
- Fixed widths that cause horizontal scrolling at 320 CSS pixels.
- Hiding essential content on mobile without an equivalent path.
- Using color alone to communicate status.

## Error handling
Preserve safe form input after validation or network failure. Announce dynamic
errors appropriately, move focus only when it helps recovery, and provide a
clear next action. Do not remove field context when rendering an error.

## Optimization
Prefer a small set of layout breakpoints and intrinsic sizing over device
sniffing. Avoid layout shifts, oversized DOM trees, and unnecessary UI libraries.
Measure interaction latency before optimizing rendering.

## Tests and validation
Test keyboard-only use, focus visibility/order, validation and recovery,
screen-reader names, contrast, 200% zoom, and small/large viewports. Run
automated accessibility checks and manual assistive-technology checks when
available; report each separately.

## Delivery checklist
- [ ] User goal and interaction states are covered
- [ ] Layout reflows with text scaling and mobile widths
- [ ] Keyboard and assistive technology paths are usable
- [ ] Errors are associated, announced, and recoverable
- [ ] Responsive and accessibility evidence is recorded

## Official documentation
- [W3C WCAG 2.2](https://www.w3.org/TR/WCAG22/)
- [MDN responsive design](https://developer.mozilla.org/docs/Learn_web_development/Core/CSS_layout/Responsive_Design)
- [WAI forms tutorial](https://www.w3.org/WAI/tutorials/forms/)
