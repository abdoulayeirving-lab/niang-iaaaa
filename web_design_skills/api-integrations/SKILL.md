---
name: api-integrations
description: Integrate REST, GraphQL, WebSocket, OAuth, and webhook services with explicit contracts, authentication, retries, quotas, and error handling. Use when connecting an application to an external or internal API.
---

# API integrations

## Identity and objective
Make service boundaries explicit and resilient without leaking secrets or
claiming a remote integration works before it has been exercised.

## When to use / when not to use
Use for new or changed API clients, webhooks, OAuth, GraphQL, or WebSockets.
Do not call paid/external APIs, create credentials, or change production
integrations without explicit authorization.

## Method
1. Locate the authoritative API specification and identify version, auth,
   quota, and data classification.
2. Define request/response types, timeouts, error mapping, and retryable
   conditions.
3. Keep credentials in the approved secret store or server environment.
4. Validate webhook signatures and replay protections before processing.
5. Add bounded retries with backoff only for safe/idempotent operations.
6. Test with mocks or vendor sandbox; probe live endpoints only when approved.

## Architecture and practices
- Use explicit connect/read timeouts and cancellation.
- Do not retry non-idempotent operations without an idempotency strategy.
- Respect rate limits and `Retry-After`.
- Validate OAuth state, redirect URI, scope, and token audience as applicable.
- Avoid logging tokens, authorization headers, or full sensitive payloads.

## Tools and technologies
Use the current HTTP/GraphQL client. Consult the provider's official API
reference, [GraphQL](https://graphql.org/learn/), and the applicable
[OAuth 2.0 RFC](https://www.rfc-editor.org/rfc/rfc6749).

## Execution instructions
Build a narrow adapter around the remote API and keep provider-specific
responses out of unrelated business logic. Document required settings by
variable name, not value. If credentials or a sandbox are absent, mark the
integration `NOT TESTED`.

## Quality example
A signed webhook is verified before any state change; duplicate events are
idempotent and invalid signatures produce a non-success response without
logging the secret.

## Common errors
- Treating all HTTP errors as retryable.
- Following redirects with credentials to untrusted origins.
- Using unbounded retries or ignoring quotas.
- Returning mock data when the provider is unavailable.

## Validation criteria
Test success, invalid auth, timeout, rate limit, malformed data, duplicate
webhook, invalid signature, and cancellation. Record mock, sandbox, and live
coverage separately.

## Final checklist
- [ ] Contract and version are identified
- [ ] Authentication and secret handling are secure
- [ ] Timeouts, retry policy, and quota handling are bounded
- [ ] Webhooks are authenticated and replay-safe
- [ ] No unapproved paid/live API call was made

## References
- [GraphQL documentation](https://graphql.org/learn/)
- [OAuth 2.0 RFC 6749](https://www.rfc-editor.org/rfc/rfc6749)
- [OWASP API Security Top 10](https://owasp.org/www-project-api-security/)
