---
name: game-engineering
description: Design and implement gameplay, physics, animation, networking, and performance in Unity, Unreal Engine, or Godot. Use for game prototypes, gameplay systems, or game project maintenance.
---

# Game engineering

## Identity and objective
Build deterministic, maintainable gameplay systems that meet target platform
and performance constraints.

## When to use / when not to use
Use for gameplay, rendering, physics, game networking, and engine project
structure. Do not add paid assets, publish builds, or connect live multiplayer
services without authorization.

## Method
1. Identify engine/version, target hardware, input model, and existing
   architecture.
2. Define a small gameplay loop and state transitions.
3. Separate input, simulation, presentation, persistence, and networking.
4. Use engine lifecycle and frame/tick APIs from the installed version.
5. Profile a representative scene before optimizing.
6. Test repeatable gameplay, save/load, pause/resume, and network failure paths.

## Architecture and practices
- Keep simulation state explicit and avoid hidden global mutable state.
- Pool objects only when profiling supports it.
- Bound physics and network work per frame.
- Treat multiplayer client data as untrusted; authoritative decisions belong
  on the server when applicable.
- Manage asset licenses, memory, and platform budgets.

## Tools and technologies
Use existing [Unity](https://docs.unity3d.com/),
[Unreal Engine](https://dev.epicgames.com/documentation/en-us/unreal-engine),
or [Godot](https://docs.godotengine.org/) versions and project conventions.

## Execution instructions
Create a minimal, reproducible scene or test fixture. Avoid downloading assets,
installing plugins, signing, or publishing unless explicitly approved. Document
engine/editor requirements and target device assumptions.

## Quality example
A pause action stops gameplay simulation and audio as intended, while UI input
remains active and resuming returns to the same deterministic state.

## Common errors
- Using engine APIs from another major version.
- Optimizing based on intuition rather than profiling.
- Coupling input, gameplay state, and rendering in one monolithic script.
- Trusting client-provided score, inventory, or authority in multiplayer.

## Validation criteria
Run available engine checks, exercise input/state transitions, inspect
representative frame timing, and test save/network failures. State when the
engine/editor is unavailable.

## Final checklist
- [ ] Engine version and target platform are explicit
- [ ] Gameplay state and system boundaries are testable
- [ ] Performance is measured on representative content
- [ ] Multiplayer trust boundaries are enforced
- [ ] Assets/plugins/releases are authorized and documented

## References
- [Unity Manual](https://docs.unity3d.com/)
- [Unreal Engine documentation](https://dev.epicgames.com/documentation/en-us/unreal-engine)
- [Godot documentation](https://docs.godotengine.org/)
