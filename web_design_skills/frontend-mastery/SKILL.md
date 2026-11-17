---
name: frontend-mastery
description: Build maintainable, accessible frontend applications with HTML, CSS, JavaScript, TypeScript, React, Next.js, Vue, or Angular. Use for components, client state, browser behavior, rendering, and frontend performance.
---

# Frontend mastery

## Identity and objective
Implement the requested browser experience with semantic markup, predictable
state, responsive behavior, and the project's existing framework.

## When to use / when not to use
Use for browser UI, component architecture, routing, state, accessibility, or
frontend rendering. Do not add a framework or replace the current stack without
a clear need and approval.

## Method
1. Identify framework/version, entry points, routing, styling, and test
   conventions.
2. Define page/component boundaries and the state owner for each interaction.
3. Implement semantic structure and accessible behavior before visual polish.
4. Handle loading, empty, error, success, and disabled states.
5. Keep server/client boundaries correct for the current framework.
6. Run the existing type, lint, test, and build checks; inspect the rendered UI
   when a preview is available.

## Architecture and practices
- Prefer small components with explicit props and stable keys.
- Use TypeScript types that reflect runtime data; validate external input.
- Avoid unnecessary global state and duplicated derived state.
- Preserve hydration/server rendering rules and keep client-only code minimal.
- Use native HTML semantics and test keyboard behavior.

## Tools and technologies
Use the existing project package manager and pinned versions. Consult
[MDN HTML](https://developer.mozilla.org/en-US/docs/Web/HTML),
[React](https://react.dev/learn), [Next.js](https://nextjs.org/docs),
[Vue](https://vuejs.org/guide/), or
[Angular](https://angular.dev/overview) documentation as applicable.

## Execution instructions
Read the relevant package scripts and configuration first. Follow the
framework's documented file conventions for the installed version. Do not
silently replace project scripts or install packages outside the approved
dependency workflow.

## Quality example
A search component debounces only if needed, keeps the query in a meaningful
state owner, exposes labelled controls, and shows accessible loading/no-results
states.

## Common errors
- Using APIs from a different framework or major version.
- Mixing server-only and browser-only modules.
- Using array indexes as keys for reorderable data.
- Faking buttons with nonsemantic elements or leaving controls inert.

## Validation criteria
Check type/lint/test/build results, route behavior, keyboard operation,
responsive layout, browser console, and production warnings.

## Final checklist
- [ ] Framework conventions match the installed version
- [ ] Components and state have clear ownership
- [ ] Accessible semantics and all UI states are implemented
- [ ] No fake controls or unhandled browser errors
- [ ] Build/test evidence is reported accurately

## References
- [MDN HTML](https://developer.mozilla.org/en-US/docs/Web/HTML)
- [React Learn](https://react.dev/learn)
- [Next.js Documentation](https://nextjs.org/docs)
- [Vue Guide](https://vuejs.org/guide/)
- [Angular Overview](https://angular.dev/overview)
