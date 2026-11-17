---
name: desktop-engineering
description: Build and maintain desktop applications with Python GUI toolkits, Electron, Tauri, or native platform APIs. Use for desktop UI, packaging, process integration, settings, and updates.
---

# Desktop engineering

## Identity and objective
Deliver a desktop application that behaves predictably across its supported
platforms and does not exceed its declared system permissions.

## When to use / when not to use
Use for a GUI application, desktop packaging, native integration, or updater.
Do not invoke privileged system operations, install system software, or publish
an installer without approval.

## Method
1. Identify supported OS versions, GUI framework, packaging path, and current
   project conventions.
2. Separate UI state, application logic, persistence, and OS integration.
3. Define startup, close, recovery, update, and offline behavior.
4. Keep file/process permissions narrow and validate user-selected paths.
5. Test GUI state and process lifecycle; package only through the existing
   approved workflow.
6. Record platform-specific behavior that was not exercised.

## Architecture and practices
- Keep long-running work off the UI thread and provide cancellation/status.
- Store user settings in the platform-appropriate application data location.
- Avoid shell-string construction; pass argument arrays and validate inputs.
- Sign and verify update artifacts when the release system supports it.
- Make startup and shutdown idempotent and clean up timers, sockets, and child
  processes.

## Tools and technologies
Use the existing framework: [Python Tkinter](https://docs.python.org/3/library/tkinter.html),
[Qt for Python](https://doc.qt.io/qtforpython-6/),
[Electron](https://www.electronjs.org/docs/latest/), or
[Tauri](https://v2.tauri.app/). Check platform/API version requirements.

## Execution instructions
Use local test directories and fake services. Do not run installers or modify
system registry/services during tests. Keep signing keys and update tokens out
of source and logs.

## Quality example
A long operation runs asynchronously, reports progress, supports cancel, and
leaves the UI responsive; closing the app terminates owned resources safely.

## Common errors
- Blocking the UI thread with I/O or model calls.
- Leaving child processes running after cancellation or exit.
- Storing secrets in plain-text settings or package resources.
- Claiming Windows/macOS/Linux parity after testing one OS only.

## Validation criteria
Verify startup, primary flow, persistence, close/reopen, error paths, keyboard
accessibility, process cleanup, and packaging on each available platform.

## Final checklist
- [ ] UI remains responsive and errors are visible
- [ ] Permissions and file/process access are bounded
- [ ] Shutdown cleans up owned work
- [ ] Settings and update artifacts are protected
- [ ] Tested platform and untested platforms are listed

## References
- [Python Tkinter](https://docs.python.org/3/library/tkinter.html)
- [Qt for Python](https://doc.qt.io/qtforpython-6/)
- [Electron](https://www.electronjs.org/docs/latest/)
- [Tauri v2](https://v2.tauri.app/)
