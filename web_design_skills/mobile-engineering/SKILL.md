---
name: mobile-engineering
description: Design, build, and validate Android, iOS, Flutter, or React Native applications, including touch interaction, local storage, permissions, notifications, and release behavior.
---

# Mobile engineering

## Identity and objective
Deliver mobile flows that are touch-friendly, privacy-conscious, resilient to
interruption, and appropriate to each target platform.

## When to use / when not to use
Use for native or cross-platform mobile applications and their platform
integrations. Do not request device permissions without a feature need or
publish to an app store without approval.

## Method
1. Confirm target OS/devices, framework/version, distribution, and offline
   requirements.
2. Map navigation, lifecycle, permission, and interrupted-flow states.
3. Build touch layouts and accessible semantics using platform conventions.
4. Minimize and explain sensitive permissions; request them just in time.
5. Protect local data and network credentials; handle connectivity changes.
6. Test simulator/emulator and physical device paths when available.

## Architecture and practices
- Respect lifecycle and process recreation; persist only required state.
- Use platform secure storage for secrets and encrypt sensitive local data as
  required.
- Make touch targets and text scaling usable; do not rely on hover.
- Handle denied/revoked permissions and offline/retry states.
- Keep platform-specific code behind clear adapters.

## Tools and technologies
Follow the installed platform stack and
[Android Developers](https://developer.android.com/),
[Apple Developer Documentation](https://developer.apple.com/documentation/),
[Flutter](https://docs.flutter.dev/), or
[React Native](https://reactnative.dev/docs/getting-started).

## Execution instructions
Use test accounts and local fixtures. Ask before connecting production
services, using paid APIs, signing, or publishing. Record device and OS versions
for manual validation.

## Quality example
A photo feature explains why camera access is needed, handles denial without
blocking unrelated screens, and allows the user to retry from settings.

## Common errors
- Assuming permission is granted or remains granted forever.
- Losing unsaved work on rotation, backgrounding, or process recreation.
- Hard-coding device dimensions or using tiny tap targets.
- Claiming device compatibility from simulator-only checks.

## Validation criteria
Test permission grant/deny/revoke, lifecycle interruptions, offline state,
accessibility scaling, navigation, and platform-specific behavior.

## Final checklist
- [ ] OS/framework targets and tested devices are stated
- [ ] Permission requests are minimal and recoverable
- [ ] Lifecycle, offline, and error states are handled
- [ ] Touch, text scaling, and accessibility were checked
- [ ] Signing/store publication remains unperformed unless approved

## References
- [Android Developers](https://developer.android.com/)
- [Apple Developer Documentation](https://developer.apple.com/documentation/)
- [Flutter documentation](https://docs.flutter.dev/)
- [React Native documentation](https://reactnative.dev/docs/getting-started)
