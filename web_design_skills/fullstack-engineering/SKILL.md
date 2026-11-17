---
name: fullstack-engineering
description: Design and deliver coordinated frontend, backend, data, and deployment changes for a complete application. Use when a request spans multiple application layers or requires end-to-end feature work.
---

# Full-stack engineering

## Identity and objective
Deliver a feature across its complete user-to-data path while preserving the
project's existing architecture and security boundaries.

## When to use / when not to use
Use when a mission changes or creates frontend, API, persistence, or runtime
configuration together. Do not force a backend into a static/offline request or
choose cloud services without user authorization.

## Method
1. Inspect repository structure, build/test commands, existing API contracts,
   authentication, and data model.
2. Trace the user action through UI, API, service, and storage.
3. Define request/response and error contracts before parallel implementation.
4. Implement vertical slices in dependency order; keep validation at each
   boundary.
5. Run available checks and exercise the real flow with safe local data.
6. Document migrations, configuration, and any unverified operational step.

## Architecture and practices
- Reuse existing frameworks, conventions, and domain boundaries.
- Keep secrets server-side and enforce authorization on every protected
  operation.
- Validate inputs at trust boundaries and return stable error shapes.
- Make data migrations reversible where feasible and avoid destructive default
  behavior.
- Separate configuration from code; do not silently substitute mock data for a
  failed live service.

## Tools and technologies
Use the repository's current frontend, backend, database, and deployment
tooling. Consult each technology's official documentation and verify installed
versions before adopting APIs.

## Execution instructions
List impacted layers, contracts, data changes, and acceptance evidence. Build
one end-to-end vertical slice first. Do not deploy, provision cloud resources,
or run paid services without explicit approval.

## Quality example
A profile update has a labelled UI form, a validated authenticated endpoint,
an authorization check, a persistence operation, and a test proving both
success and rejected invalid input.

## Common errors
- Updating the UI without updating the API contract or real persistence.
- Leaving mock data in the production path.
- Performing authorization only in the frontend.
- Reporting an endpoint as working based only on compilation.

## Validation criteria
Verify frontend build/tests, backend tests, API response shape/status, database
migration behavior, and configuration prerequisites. Distinguish runtime
probes from static checks.

## Final checklist
- [ ] User flow maps to API and data changes
- [ ] Contracts, authorization, and validation are consistent
- [ ] No mock success-shaped fallback hides errors
- [ ] Relevant tests/builds and runtime probes are recorded
- [ ] Deployment and paid-service actions remain unperformed unless approved

## References
- [Microsoft Azure Architecture Center](https://learn.microsoft.com/azure/architecture/)
- [OWASP Application Security Verification Standard](https://owasp.org/www-project-application-security-verification-standard/)
