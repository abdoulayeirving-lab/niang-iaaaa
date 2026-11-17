---
name: secure-software-engineering
description: Apply defensive security to application code, APIs, identity, sensitive data, and dependencies. Use when a change handles untrusted input, authorization, secrets, file/process access, or security findings.
---

# Secure software engineering

## Objective and scope
Reduce concrete security risk using least privilege, secure defaults, and
verifiable controls. Work only in authorized repositories and environments;
this is defensive engineering, not permission to probe third-party systems.

## When to use
Use for authn/authz, input/output boundaries, file paths, subprocesses, secrets,
payments, data protection, dependencies, and security-sensitive reviews. Do not
disable a control or run exploit workflows to satisfy an unrelated request.

## Compatible technologies
Apply the current framework's secure defaults for Python, JavaScript/TypeScript,
Java, C#, Go, Rust, PHP, databases, and deployment config. Consult the framework
version and security advisories applicable to the locked dependencies.

## Professional method
1. Identify assets, trust boundaries, attacker-controlled inputs, and
   authorization decisions.
2. Define an abuse case and the server-side control that prevents it.
3. Validate input, encode output, authorize each resource, and minimize stored
   and logged data.
4. Store credentials in approved secret management; rotate only when authorized.
5. Add negative tests for denied, malformed, cross-user, and boundary cases.
6. Review residual risk and report exactly which checks were executed.

## Recommended architecture
Enforce access at the authoritative server/service boundary. Separate
authentication from per-resource authorization; validate ownership before
reading or mutating data. Keep secrets outside source, prompts, browser bundles,
logs, and test fixtures.

## Code examples
Parameterize queries and authorize the requested record before returning it:

```python
def get_document(connection, user_id: str, document_id: str):
    row = connection.execute(
        "SELECT id, owner_id, title FROM documents WHERE id = ?",
        (document_id,),
    ).fetchone()
    if row is None or row["owner_id"] != user_id:
        return None
    return row
```

The database placeholder syntax is driver-specific; use the installed driver's
documented parameter binding rather than string interpolation.

## Best practices
- Deny by default and grant only the narrow permission required.
- Treat files, prompts, model output, URLs, and API responses as untrusted.
- Use parameterized data access and context-aware output encoding.
- Validate paths after canonicalization and constrain them to an approved root.
- Redact tokens, passwords, private data, and authorization headers.

## Anti-patterns
- Client-side checks used as the only authorization boundary.
- Prompt instructions treated as a security control.
- Building SQL, shell commands, or HTML with untrusted string concatenation.
- Broad exception handling that turns denied access into success.
- Logging full request bodies or environment variables.

## Error handling
Return consistent, non-sensitive errors; avoid leaking whether another user's
resource exists. Log enough structured context for diagnostics without
credentials or payloads. Fail closed when authorization, key retrieval, or
validation cannot complete.

## Optimization
Avoid redundant authorization queries by using well-scoped request context, but
never cache permission decisions beyond their correct identity and lifetime.
Use safe indexes and bounded payloads; do not trade tenant isolation for
throughput.

## Tests and validation
Test allowed and denied principals, resource ownership, malformed values,
secret redaction, and relevant abuse cases. Use only local fixtures and
authorized scanners; do not scan external targets or transmit repository data.

## Delivery checklist
- [ ] Assets, trust boundaries, and authorization owner are identified
- [ ] Server-side controls deny unauthorized access
- [ ] Inputs, outputs, paths, and secrets are handled safely
- [ ] Negative security tests pass
- [ ] No protection was weakened and residual risks are documented

## Official documentation
- [OWASP ASVS](https://owasp.org/www-project-application-security-verification-standard/)
- [OWASP Cheat Sheet Series](https://cheatsheetseries.owasp.org/)
- [OWASP API Security Top 10](https://owasp.org/www-project-api-security/)
