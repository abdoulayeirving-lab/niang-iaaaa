---
name: senior-fullstack-engineering
description: Deliver complete features across a frontend, API, persistence, and deployment boundary while preserving contracts and adding end-to-end validation. Use for full-stack or multi-layer application work.
---

# Senior full-stack engineering

## Objective and scope
Ship coherent end-to-end behavior, not disconnected frontend and backend
snippets. Coordinate UI state, API contracts, authorization, persistence, and
operational behavior. Do not invent missing product or data policies.

## When to use
Use when a request spans client and server, new application scaffolding, or a
user flow that must be wired to live data. For an isolated layer change, use its
specialist skill and avoid unnecessary full-stack restructuring.

## Compatible technologies
Follow the installed stack: React/Vue/Angular and TypeScript, Node/Express/
NestJS, Python/FastAPI/Django, Java/Spring, .NET, Go, and the repository's
database/ORM. Confirm framework versions from manifests and lockfiles.

## Professional method
1. Trace the existing user flow, API endpoints, schema, auth model, and tests.
2. Define request/response and error contracts before parallel UI/API edits.
3. Identify ownership, validation, transaction, loading, empty, and retry states.
4. Implement a vertical slice from persistence through API to UI.
5. Add contract and integration tests at the narrowest useful layers.
6. Verify migrations, all required endpoints, and the real UI path when safely
   possible; report unavailable environments as `NOT TESTED`.

## Recommended architecture
Keep presentation state in the client, business rules in an application/domain
layer, and persistence behind existing repositories or data access. Use typed
DTOs at API boundaries; do not expose ORM entities or secrets to the browser.
Keep authorization checks server-side and close to resource access.

## Code examples
Define one explicit API contract and handle expected failure in the client:

```ts
type CreateTask = { title: string };
type Task = { id: string; title: string; status: "open" | "done" };

async function createTask(input: CreateTask): Promise<Task> {
  const response = await fetch("/api/tasks", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!response.ok) {
    throw new Error(`Task creation failed (${response.status}).`);
  }
  return (await response.json()) as Task;
}
```

The server must still validate and authorize independently; a typed client
contract is not a security boundary.

## Best practices
- Keep schema/API/UI field names and nullability aligned.
- Use server-side validation and explicit error responses.
- Use transactions for multi-write invariants; design migrations for safe
  rollout and rollback.
- Make loading, empty, success, failure, and retry states visible.
- Use one source of truth for configuration and generated contracts when
  available.

## Anti-patterns
- Frontend mock data left connected after backend implementation.
- Duplicated business rules that diverge between client and server.
- Silent mock fallbacks when the API fails.
- Shipping destructive schema changes before dependent code is compatible.
- Treating a successful compile as proof that the user flow works.

## Error handling
Map validation, conflict, authorization, unavailable, and unexpected failures
to distinct server responses. Preserve correlation context without logging
credentials or sensitive request bodies. The client should show a recoverable
message and retain safe user input when possible.

## Optimization
Measure page/API latency and database query count. Paginate large collections,
avoid N+1 queries, load only required fields, and apply caching only with
explicit ownership and invalidation rules. Do not optimize from assumptions.

## Tests and validation
Test API contracts, authorization boundaries, persistence behavior, and the
client's loading/error states. Run migrations against a disposable database
when available; smoke-test every changed endpoint. Browser/device validation is
`NOT TESTED` unless actually performed.

## Delivery checklist
- [ ] UI is wired to the real API and schema
- [ ] Server validates, authorizes, and handles errors
- [ ] Migration and data compatibility are addressed
- [ ] Focused unit/contract/integration tests pass
- [ ] Runtime/browser checks and remaining gaps are reported honestly

## Official documentation
- [React](https://react.dev/learn)
- [TypeScript](https://www.typescriptlang.org/docs/)
- [FastAPI](https://fastapi.tiangolo.com/)
- [ASP.NET Core APIs](https://learn.microsoft.com/aspnet/core/web-api/)
