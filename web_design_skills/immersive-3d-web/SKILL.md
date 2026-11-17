---
name: immersive-3d-web
description: Build accessible, performant browser-based 3D experiences with WebGL, Three.js, or React Three Fiber. Use when a web project explicitly needs interactive 3D, shaders, product viewers, or immersive scenes.
---

# Immersive 3D web

## Identity and objective
Use 3D as progressive enhancement that supports the task. The essential
content and controls must remain available when WebGL is unavailable or
reduced.

## When to use / when not to use
Use for a meaningful 3D scene, viewer, visualization, or spatial interaction.
Do not add WebGL to a content-first page without a user benefit, or replace
essential text/navigation with a canvas.

## Method
1. Confirm browser/device targets, scene purpose, assets, and fallback.
2. Check installed Three.js and renderer versions before using APIs.
3. Define camera, lighting, material, scene bounds, and interaction model.
4. Load large assets asynchronously with an explicit loading/error state.
5. Reuse geometry/materials and limit draw calls; profile on target hardware.
6. Provide keyboard/touch controls and a non-3D equivalent for important
   information.

## Architecture and practices
- In React Three Fiber, place hooks such as `useFrame` inside a component under
  `<Canvas>` and mutate refs rather than querying the DOM for scene objects.
- Use actual Three.js geometry elements such as `boxGeometry` and
  `sphereGeometry`; do not invent JSX primitives.
- Dispose custom GPU resources when their lifecycle requires it.
- Clamp pixel ratio and scene complexity on constrained devices.
- Do not fetch untrusted remote models or shaders without a clear origin policy.

## Tools and technologies
Use the project's existing [Three.js](https://threejs.org/docs/) or
[React Three Fiber](https://r3f.docs.pmnd.rs/) versions. Use standard WebGL
capability checks and browser performance tools.

## Execution instructions
Start with a minimal scene and fallback, then add lighting, materials, and
interaction one change at a time. Keep assets in the project's approved asset
directory and document their source/license. Avoid unapproved package
installation.

## Quality example
A product viewer has bounded orbit controls, an accessible text description,
loading/error feedback, and a static image fallback that still exposes product
details and purchase actions.

## Common errors
- Calling React hooks outside a React component or Canvas context.
- Using imaginary geometry/material components or unverified prop shapes.
- Creating a high-cost scene with many unique meshes and large textures.
- Making the canvas the only way to access product or data information.

## Validation criteria
Verify scene load and failure paths, keyboard/touch controls, fallback,
resource cleanup, and measured performance on the available target device.
Record unavailable hardware/browser checks as `NOT TESTED`.

## Final checklist
- [ ] 3D provides a documented user benefit
- [ ] Framework and Three.js APIs match installed versions
- [ ] Fallback and accessible equivalent are present
- [ ] Assets are licensed and bounded in size
- [ ] Controls, cleanup, and performance were checked

## References
- [Three.js documentation](https://threejs.org/docs/)
- [React Three Fiber documentation](https://r3f.docs.pmnd.rs/)
- [MDN WebGL API](https://developer.mozilla.org/en-US/docs/Web/API/WebGL_API)
