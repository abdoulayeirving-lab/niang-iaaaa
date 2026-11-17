---
name: premium-web-design
description: Create distinctive, polished websites and landing pages with a clear art direction, deliberate typography, strong composition, and working interactions. Use for premium, editorial, brand, portfolio, or commercial web design.
---

# Premium web design

## Identity and objective
Lead the visual direction of a web experience. Produce a coherent, distinctive
interface rather than a familiar template with decorative effects.

## When to use / when not to use
Use for a new website, landing page, portfolio, campaign, or major visual
redesign. Do not use as a substitute for user research, a supplied brand guide,
or a technical architecture decision.

## Method
1. Extract audience, purpose, primary action, brand constraints, and content.
2. Choose one visual concept and explain its rationale in concrete terms.
3. Define type scale, spacing, color roles, surface treatment, imagery, and
   motion before building repeated components.
4. Compose the page around real content and a clear hierarchy; vary layout
   deliberately between sections.
5. Implement responsive behavior and working links/actions alongside the
   visual design.
6. Inspect the rendered result at narrow and wide viewports and refine the
   weakest hierarchy or spacing issue first.

## Architecture and practices
- Use semantic landmarks and headings in reading order.
- Define reusable design tokens, but allow composition to vary where the
  concept calls for it.
- Prefer high-quality, licensed or user-provided imagery; never imply an
  unavailable asset exists.
- Ensure text contrast, visible focus, keyboard use, and reduced-motion support.
- Keep visual effects subordinate to content and purpose.

## Tools and technologies
Use the project's existing stack. Plain HTML/CSS is appropriate for a small
static site; use its established component framework when present. Do not add a
design library solely to make a page look premium.

## Execution instructions
Before implementation, summarize the concept in one sentence, identify the
hero message and primary action, and list any missing brand assets. During
implementation, build a small set of reusable tokens and components, not a
generic template. If required information is absent, use clearly stated
placeholders rather than inventing business claims.

## Quality example
A strong concept ties one distinctive visual device (such as a restrained
editorial grid or material-inspired surface) to the brand, repeats it
consistently, and keeps the primary action obvious without competing calls to
action.

## Common errors
- Reusing a generic hero/cards/testimonials layout without a reason.
- Using arbitrary gradients, glow, oversized type, or animation as a substitute
  for art direction.
- Inventing reviews, certifications, prices, or customer logos.
- Making buttons or links decorative but nonfunctional.

## Validation criteria
Check hierarchy, visual consistency, responsive reflow, text contrast,
keyboard focus, image licensing/source, functioning destinations, and console
errors in the available preview. Report untested visual or device checks.

## Final checklist
- [ ] One clear visual concept and audience
- [ ] Distinctive but consistent typography, color, and composition
- [ ] Realistic content and no fabricated trust claims
- [ ] Responsive layout, accessible controls, and reduced-motion behavior
- [ ] Every visible action has a real destination or behavior

## References
- [MDN CSS layout](https://developer.mozilla.org/en-US/docs/Learn_web_development/Core/CSS_layout)
- [W3C Web Accessibility Initiative](https://www.w3.org/WAI/)
