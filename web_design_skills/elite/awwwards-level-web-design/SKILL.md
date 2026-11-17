---
name: awwwards-level-web-design
description: Art-direct distinctive, polished websites with strong typography, composition, responsive behavior, accessibility, and functional details. Use for premium landing pages, brand sites, portfolios, and high-fidelity web experiences.
---

# Awwwards-level web design

## Objective and scope
Create an original and coherent visual system that communicates the product
clearly and works across devices. “Award-level” means deliberate art direction
and polished execution, not visual effects at the cost of usability.

## When to use
Use for premium brand, editorial, portfolio, campaign, or product pages. Do
not copy an existing site's distinctive design; use references only to discuss
general visual qualities and create an original composition.

## Compatible technologies
Use the existing HTML/CSS and frontend framework (React, Next.js, Vue, etc.).
Use CSS for simple motion, Motion for React interactions, GSAP for complex
timelines, and Three.js only for a justified 3D scene.

## Professional method
1. Learn the audience, action, content hierarchy, brand constraints, and assets.
2. Define a one-sentence art direction and a small set of design tokens.
3. Sketch the page hierarchy and responsive behavior before polishing details.
4. Build semantic, reusable sections with real content and working navigation.
5. Add motion only after the static composition works.
6. Validate keyboard, screen reader semantics, mobile, reduced motion,
   performance, and every interactive control.

## Recommended architecture
Separate content/data, page composition, reusable UI components, and design
tokens. Keep one owner for each stateful interaction. Use existing routing and
asset pipelines; do not introduce a new UI framework for a single page.

## Code examples
Use a semantic hero with an explicit primary action:

```html
<main>
  <section class="hero" aria-labelledby="hero-title">
    <p class="eyebrow">Independent design studio</p>
    <h1 id="hero-title">A clear idea, beautifully made.</h1>
    <p class="hero__summary">A concise statement of what the studio delivers.</p>
    <a class="button" href="#work">Explore selected work</a>
  </section>
</main>
```

## Best practices
- Use a recognizable type scale, readable line lengths, intentional whitespace,
  and strong contrast.
- Pair expressive display typography with legible body text.
- Use original or licensed assets; set image dimensions and useful alt text.
- Keep calls to action obvious and navigation predictable.
- Make empty, loading, hover, focus, active, and error states intentional.

## Anti-patterns
- Generic template composition with unrelated gradients and card grids.
- Tiny low-contrast text, illegible overlays, or text embedded in images.
- Decorative motion that blocks navigation or steals focus.
- Fake links, placeholder content, or nonfunctional “premium” buttons.
- Copying another site's exact layout, text, or visual identity.

## Error handling
Provide a designed fallback for missing images, failed forms, and unavailable
remote data. Keep the primary content usable if decorative assets or animation
fail to load. Do not mask broken links or silently drop form errors.

## Optimization
Use responsive image sources, modern formats already supported by the project,
font subsetting only when existing tooling supports it, and lazy-load below-fold
media. Profile before adding animation libraries or complex rendering.

## Tests and validation
Check layout at narrow, medium, and wide widths; tab order; visible focus;
contrast; headings; link destinations; form errors; reduced-motion behavior;
and loading performance. Run browser/E2E checks only when the environment
supports them and record what was not tested.

## Delivery checklist
- [ ] Art direction and hierarchy are clear and original
- [ ] All actions and links work
- [ ] Mobile and desktop layouts are intentional
- [ ] Keyboard, contrast, semantics, and reduced motion are considered
- [ ] Assets are licensed and performance was checked

## Official documentation
- [MDN HTML](https://developer.mozilla.org/docs/Web/HTML)
- [MDN CSS](https://developer.mozilla.org/docs/Web/CSS)
- [W3C WCAG 2.2](https://www.w3.org/TR/WCAG22/)
- [web.dev performance](https://web.dev/learn/performance/)
