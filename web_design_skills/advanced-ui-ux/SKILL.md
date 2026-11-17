---
name: advanced-ui-ux
description: Design usable, accessible interfaces through user goals, information architecture, interaction states, and reusable design systems. Use for dashboards, forms, workflows, product interfaces, or UX redesigns.
---

# Advanced UI/UX

## Identity and objective
Turn user goals into an understandable, testable interface. Optimize for
successful task completion, not visual novelty alone.

## When to use / when not to use
Use when designing flows, forms, dashboards, settings, or reusable components.
Do not infer user research results that were not supplied or replace a required
domain/security review.

## Method
1. Identify user roles, goals, constraints, and the most important task.
2. Map the information architecture and primary/alternate user journey.
3. Sketch the states and transitions before styling.
4. Define components, tokens, and interaction patterns from the existing
   design system; add a system only when needed.
5. Implement loading, empty, success, error, disabled, and permission states.
6. Test the main flow with keyboard and realistic data; revise confusing steps.

## Architecture and practices
- Prefer semantic HTML and native controls before custom widgets.
- Preserve visible labels, logical tab order, focus management, and useful
  validation messages.
- Use consistent component APIs and document variants and states.
- Keep destructive actions distinct and provide an undo or confirmation where
  appropriate.
- Treat accessibility as a design constraint from the first wireframe.

## Tools and technologies
Use the current application component framework and its established design
system. Use browser accessibility inspection and automated checks when
available; automated results do not replace manual keyboard review.

## Execution instructions
Record the critical user journey and its success outcome. For each interactive
component, specify its default, hover, focus, active, disabled, loading, and
error states as relevant. Ask for clarification when role permissions or data
semantics materially change the flow.

## Quality example
A validated form preserves entered values, associates errors with fields,
announces the error summary, and moves focus to the first actionable error.

## Common errors
- Designing only the happy path.
- Using placeholder text as the only field label.
- Hiding focus indicators or relying on color alone.
- Creating a large component with undocumented state combinations.

## Validation criteria
Verify the primary flow, keyboard-only navigation, focus visibility, labels,
error recovery, empty/loading states, and responsive use. Record which checks
were automated and which were manual.

## Final checklist
- [ ] Primary user goal and flow are explicit
- [ ] Every meaningful state is represented
- [ ] Controls have labels, focus, and keyboard behavior
- [ ] Errors are actionable and preserve user work
- [ ] Components match the design system and have bounded variants

## References
- [W3C WCAG 2.2](https://www.w3.org/TR/WCAG22/)
- [WAI-ARIA Authoring Practices](https://www.w3.org/WAI/ARIA/apg/)
- [MDN HTML forms](https://developer.mozilla.org/en-US/docs/Learn_web_development/Extensions/Forms)
