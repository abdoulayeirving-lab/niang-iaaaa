---
name: threejs-webgl-mastery
description: Build interactive browser-based 3D with Three.js or React Three Fiber, including lifecycle, accessibility fallbacks, asset budgets, and GPU-aware rendering. Use only when a web task explicitly requires 3D.
---

# Three.js and WebGL mastery

## Objective and scope
Add a purposeful, performant 3D experience that works as a progressive
enhancement and does not block the site's core content or actions.

## When to use
Use for a 3D product viewer, scene, spatial interaction, or shader effect that
cannot be represented adequately with DOM/CSS. Do not use Three.js for simple
parallax, flat illustration, or ordinary transitions.

## Compatible technologies
Use the installed Three.js version directly or React Three Fiber within React.
Confirm the renderer/API version, asset pipeline, and target browser/device.
Use only authorized/licensed models, textures, and fonts.

## Professional method
1. Define what 3D enables for the user's task and a useful non-3D fallback.
2. Set budgets for polygons, textures, draw calls, memory, and frame rate.
3. Load assets asynchronously with progress, cancellation, and failure states.
4. Handle resize, visibility, pointer, touch, and reduced-motion behavior.
5. Dispose geometry, materials, textures, renderer, and listeners on teardown.
6. Profile on target mobile devices and verify context-loss/failure handling.

## Recommended architecture
Keep scene construction, asset loading, controls, and DOM UI as separate
responsibilities. In React, let React Three Fiber own renderer lifecycle; do
not mutate the same scene from competing imperative loops. Keep HTML controls
semantic and outside the canvas where possible.

## Code examples
An explicit cleanup path for an imperative renderer:

```ts
function disposeScene(
  renderer: THREE.WebGLRenderer,
  geometries: THREE.BufferGeometry[],
  materials: THREE.Material[],
): void {
  geometries.forEach((geometry) => geometry.dispose());
  materials.forEach((material) => material.dispose());
  renderer.dispose();
}
```

## Best practices
- Provide an accessible text/DOM alternative for scene information and actions.
- Pause rendering when the tab is hidden or the scene is offscreen.
- Respect reduced motion; avoid forced camera movement.
- Use compressed textures/models when supported by the current asset pipeline.
- Handle WebGL unsupported, context lost, and asset failure states.

## Anti-patterns
- Starting multiple render loops or leaving animation frames running after
  unmount.
- Huge uncompressed textures or excessive draw calls on mobile.
- Canvas-only controls without keyboard or screen-reader alternatives.
- Downloading model assets without confirming licensing.
- Adding 3D because it looks impressive but does not support a user goal.

## Error handling
Catch asset-load and renderer initialization failures at their boundary, show a
useful fallback, and keep the rest of the page usable. Listen for WebGL context
loss when relevant; do not silently render a blank canvas.

## Optimization
Profile GPU and CPU separately. Reuse geometries/materials, cap pixel ratio,
limit shadows/post-processing, and avoid unnecessary per-frame allocations.
Use instancing only when it benefits measured repeated geometry.

## Tests and validation
Test mount/unmount disposal, loading/error states, resize, keyboard controls,
reduced motion, and fallback content. Verify frame stability, memory, and
context behavior on representative mobile hardware when available.

## Delivery checklist
- [ ] The user need justifies 3D over DOM/CSS
- [ ] Accessible fallback and controls are present
- [ ] Renderer/assets/listeners are disposed correctly
- [ ] Mobile GPU, memory, and reduced-motion paths are checked
- [ ] Asset licensing and untested devices are documented

## Official documentation
- [Three.js](https://threejs.org/docs/)
- [React Three Fiber](https://r3f.docs.pmnd.rs/)
- [MDN WebGL best practices](https://developer.mozilla.org/docs/Web/API/WebGL_API/WebGL_best_practices)
