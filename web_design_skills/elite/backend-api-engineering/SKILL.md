---
name: backend-api-engineering
description: Design reliable, secure HTTP APIs and backend services with explicit contracts, validation, authorization, persistence, observability, and compatibility. Use for API endpoints, workers, and service boundaries.
---

# Backend API engineering

## Objective and scope
Deliver a backend contract that clients can use safely and operators can
diagnose. Keep transport, business rules, and persistence responsibilities
separate enough to test without adding unnecessary layers.

## When to use
Use for REST/GraphQL endpoints, webhooks, background jobs, or service logic.
For a complete frontend-to-database feature, combine with
`senior-fullstack-engineering`.

## Compatible technologies
Use the existing FastAPI/Django, Express/NestJS, Spring, ASP.NET Core, Go, or
other service stack. Check framework, runtime, ORM, and database versions from
the manifests and lockfiles.

## Professional method
1. Define resource model, method, request/response, status, and error contract.
2. Validate input and size before expensive work.
3. Authenticate the caller and authorize each resource action server-side.
4. Apply domain invariants and transactions at the service/data boundary.
5. Add structured logs/metrics without sensitive payloads.
6. Test contracts, ownership, failure paths, and runtime routes.

## Recommended architecture
Keep HTTP controllers thin: parse/validate, delegate domain behavior, map
results/errors. Use typed request/response DTOs rather than serializing database
entities. Use repositories only where they clarify transaction/query ownership.
Version public contracts deliberately.

## Code examples
A typed FastAPI endpoint validates input and returns a stable response:

```python
from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI()


class CreateItem(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class ItemResponse(BaseModel):
    id: str
    title: str


@app.post("/api/items", response_model=ItemResponse, status_code=201)
def create_item(body: CreateItem) -> ItemResponse:
    item = item_service.create(title=body.title)
    return ItemResponse(id=item.id, title=item.title)
```

In a real application, inject the service using the project's established
dependency mechanism and authorize the caller before performing the mutation.

## Best practices
- Return predictable status codes and a documented error schema.
- Use pagination, filtering, and request-size limits for collections and uploads.
- Make retries safe with idempotency where a request may be repeated.
- Verify webhook signatures and replay policy at the trusted boundary.
- Use transactions and timeouts for external dependencies.

## Anti-patterns
- Trusting client-supplied owner IDs or role claims without verification.
- Returning raw exception text, ORM objects, or unbounded collections.
- Retrying non-idempotent operations without a deduplication strategy.
- Treating HTTP 200 as a generic error response.
- Logging secrets or full sensitive request/response bodies.

## Error handling
Map validation, unauthenticated, forbidden, missing, conflict, dependency
failure, and unexpected errors distinctly. Add correlation IDs and actionable
logs, but redact credentials and personal information. Fail closed when policy
or required dependencies are unavailable.

## Optimization
Use database query plans, indexes, pagination, connection pools, and bounded
concurrency based on measurement. Avoid N+1 queries and unbounded queues. Add
caching only with clear tenant scope, freshness, and invalidation.

## Tests and validation
Test schema validation, status/body contracts, access control, transaction
behavior, retries, and dependency failure. Start the service and probe every
changed endpoint when the environment allows; distinguish test mocks from
runtime evidence.

## Delivery checklist
- [ ] Contract and compatibility are documented
- [ ] Authentication and per-resource authorization are enforced
- [ ] Input, errors, retries, and transactions are bounded
- [ ] Tests cover contract, denied access, and failure paths
- [ ] Runtime endpoint results and gaps are stated

## Official documentation
- [FastAPI](https://fastapi.tiangolo.com/)
- [OpenAPI Specification](https://spec.openapis.org/oas/latest.html)
- [OWASP API Security](https://owasp.org/www-project-api-security/)
- [Microsoft REST API Guidelines](https://github.com/microsoft/api-guidelines)
