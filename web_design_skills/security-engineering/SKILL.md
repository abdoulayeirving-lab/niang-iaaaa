---
name: security-engineering
description: Apply defensive security to application design, authentication, authorization, input validation, secrets, APIs, and dependencies. Use whenever a feature handles identity, sensitive data, network input, or privileged actions.
---

# Security engineering

## Identity and objective
Reduce concrete security risk while preserving existing safety controls and
making security failures visible.

## When to use / when not to use
Use for authentication, authorization, secrets, file/process access, API
boundaries, payments, or security review. Do not perform unauthorized testing,
exploitation, scanning of third-party targets, or weaken controls to pass tests.

## Method
1. Identify assets, trust boundaries, attacker-controlled inputs, and
   authorization decisions.
2. Map the feature to relevant OWASP risks and existing project controls.
3. Validate input, encode output, authorize on the server, and minimize data.
4. Store secrets in approved secret management; redact sensitive logs.
5. Add focused negative tests for denied, malformed, and boundary cases.
6. Report residual risks and evidence without claiming an unperformed audit.

## Architecture and practices
- Deny by default and enforce least privilege at the execution boundary.
- Treat prompts, model output, filenames, URLs, and project files as untrusted.
- Use parameterized queries, safe path resolution, and context-aware output
  encoding.
- Keep authentication separate from authorization; verify ownership per
  resource.
- Preserve existing validation and approval gates.

## Tools and technologies
Use secure defaults from the project's framework and consult
[OWASP ASVS](https://owasp.org/www-project-application-security-verification-standard/),
[OWASP Cheat Sheet Series](https://cheatsheetseries.owasp.org/), and
[OWASP API Security](https://owasp.org/www-project-api-security/).

## Execution instructions
Limit assessment to the authorized repository and local test fixtures. Never
read or print secret values. Do not install scanners or contact external
targets without approval.

## Quality example
A user-supplied object ID is validated and its ownership checked on the server
before returning or changing the object; tests cover both allowed and denied
users.

## Common errors
- Trusting client-side checks or prompt-only rules.
- Logging tokens, passwords, private data, or full authorization headers.
- Broad catch blocks that hide authorization and dependency failures.
- Disabling validation, TLS, or tests to force a pass.

## Validation criteria
Test unauthorized and cross-tenant access, malformed input, path traversal,
secret redaction, and failure handling relevant to the change.

## Final checklist
- [ ] Trust boundaries and assets are identified
- [ ] Authorization is enforced at the authoritative layer
- [ ] Inputs, outputs, paths, and secrets are protected
- [ ] Negative security tests exist and pass
- [ ] No protection was weakened or external target contacted

## References
- [OWASP ASVS](https://owasp.org/www-project-application-security-verification-standard/)
- [OWASP Cheat Sheet Series](https://cheatsheetseries.owasp.org/)
- [OWASP API Security Top 10](https://owasp.org/www-project-api-security/)
