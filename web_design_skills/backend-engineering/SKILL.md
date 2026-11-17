---
name: backend-engineering
description: Design and implement reliable server-side services, APIs, authentication, validation, and error handling in Python, Node.js, Java, PHP, Go, or C#. Use for backend endpoints, workers, and service logic.
---

# Backend engineering

## Identity and objective
Build server behavior that enforces domain rules, protects data, and reports
failures explicitly.

## When to use / when not to use
Use for APIs, workers, scheduled jobs, or server-side business logic. Do not
create a server for a static/offline requirement or choose a cloud host without
approval.

## Method
1. Inspect runtime/framework versions, routes, middleware, tests, and config.
2. Define inputs, outputs, side effects, authorization, and failure cases.
3. Validate input at boundaries and apply domain rules in the service layer.
4. Keep handlers thin; use existing dependency injection and transaction
   patterns.
5. Add structured, privacy-safe logs and explicit error mapping.
6. Build, run focused tests, and probe endpoints when runtime is available.

## Architecture and practices
- Authenticate identity and authorize each operation server-side.
- Use parameterized data access and bounded timeouts.
- Make retries safe for side-effecting requests through idempotency where
  appropriate.
- Do not log credentials, tokens, or sensitive payloads.
- Fail clearly; never return fake successful data on dependency errors.

## Tools and technologies
Follow the current project's language/framework. Primary references include
[Python](https://docs.python.org/3/),
[Node.js](https://nodejs.org/docs/latest/api/),
[FastAPI](https://fastapi.tiangolo.com/),
[Spring Boot](https://docs.spring.io/spring-boot/index.html),
[ASP.NET Core](https://learn.microsoft.com/aspnet/core/), and
[Go](https://go.dev/doc/).

## Execution instructions
Use the repository's package manager and environment. Document required
configuration by key name only, never by secret value. Require explicit
approval before migrations, deployment, or external service changes.

## Quality example
An API endpoint validates the payload, checks the authenticated user's
permission, commits a transaction, and returns a documented status and response
shape; its tests cover invalid and unauthorized requests.

## Common errors
- Trusting client-supplied user IDs or role claims.
- Catching all exceptions and converting them into HTTP 200 success.
- Running unbounded queries or background work inside request handlers.
- Assuming an endpoint works because the project compiles.

## Validation criteria
Test success, validation, unauthorized/forbidden, not-found, conflict, and
dependency failure paths. Run a real local request when safe and available.

## Final checklist
- [ ] Boundary validation, authentication, and authorization are explicit
- [ ] Errors are visible and do not masquerade as success
- [ ] Transactions, timeouts, retries, and logs are bounded
- [ ] Secrets and sensitive payloads are not logged
- [ ] Endpoint probes and test outcomes are recorded

## References
- [Python documentation](https://docs.python.org/3/)
- [Node.js API](https://nodejs.org/docs/latest/api/)
- [FastAPI documentation](https://fastapi.tiangolo.com/)
- [Spring Boot documentation](https://docs.spring.io/spring-boot/index.html)
- [ASP.NET Core documentation](https://learn.microsoft.com/aspnet/core/)
- [Go documentation](https://go.dev/doc/)
