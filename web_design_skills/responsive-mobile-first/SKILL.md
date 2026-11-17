---
name: responsive-mobile-first
description: Design and verify responsive, mobile-first interfaces across viewport sizes, input methods, and orientations. Use for websites, web apps, navigation, responsive content, or mobile usability work.
---

# Responsive mobile-first

## Identity and objective
Make content and tasks work across viewport sizes without clipping, hidden
functionality, or device-specific assumptions.

## When to use / when not to use
Use for any web interface or when repairing layout behavior. Do not equate
responsive design with a set of fixed device names or assume a CSS framework's
default breakpoints are requirements.

## Method
1. Identify content priority and narrowest supported viewport.
2. Build the simplest narrow layout first; add breakpoints when content needs
   them.
3. Use flexible grid/flex sizing, intrinsic content, and fluid type where
   appropriate.
4. Adapt navigation and controls for touch and keyboard.
5. Test real content at narrow, medium, and wide widths and both orientations.
6. Fix overflow, target sizing, and reading-order issues before decorative
   refinements.

## Architecture and practices
- Prefer CSS grid/flex and `minmax`, `clamp`, and container-aware sizing over
  arbitrary fixed widths.
- Keep DOM reading order meaningful when visual layouts change.
- Provide intrinsic image dimensions and responsive sources when available.
- Do not hide important content solely to fit a small screen.
- Support zoom, text resizing, reduced motion, and touch spacing.

## Tools and technologies
Use project CSS conventions and browser responsive inspection. Follow the
[MDN responsive design guide](https://developer.mozilla.org/en-US/docs/Learn_web_development/Core/CSS_layout/Responsive_Design).

## Execution instructions
Choose viewport checks based on content breakpoints, including at least one
narrow phone, one tablet-like width, and one desktop width. Record exact widths
tested; never claim testing on a physical device unless one was used.

## Quality example
A two-column product layout becomes a single readable column at the point where
the product image, summary, and actions would otherwise become cramped; no
content or controls are removed.

## Common errors
- Invalid nested media-query syntax or duplicate/conflicting declarations.
- Designing to named devices rather than content constraints.
- Fixed-width images or controls that cause horizontal scrolling.
- Relying on hover for actions that must work on touch.

## Validation criteria
Check horizontal overflow, text zoom, navigation, orientation, focus order,
touch targets, image sizing, and key actions across tested widths.

## Final checklist
- [ ] Narrow-first content order and layout are clear
- [ ] No unintended horizontal scroll or clipped controls
- [ ] Touch, keyboard, zoom, and orientation work
- [ ] Responsive media and typography are bounded
- [ ] Tested viewports are recorded accurately

## References
- [MDN responsive design](https://developer.mozilla.org/en-US/docs/Learn_web_development/Core/CSS_layout/Responsive_Design)
- [W3C WCAG 2.2](https://www.w3.org/TR/WCAG22/)
