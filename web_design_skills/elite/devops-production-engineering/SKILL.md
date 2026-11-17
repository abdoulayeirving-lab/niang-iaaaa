---
name: devops-production-engineering
description: Prepare reproducible builds, least-privilege CI, deployment safety, observability, health checks, and recovery for production systems. Use for release and operational-readiness work; deployments require explicit approval.
---

# DevOps and production engineering

## Objective and scope
Make releases repeatable, observable, and recoverable. This skill can prepare
and validate code/configuration; it does not authorize provisioning, publishing,
or production deployment.

## When to use
Use for CI/CD, containers, infrastructure handoff, monitoring, backups, and
rollback planning. Ask before connecting credentials, pushing artifacts, or
changing a live environment.

## Compatible technologies
Reuse existing GitHub Actions/Azure Pipelines, Docker, Kubernetes, Terraform,
Bicep, or platform-native tooling. Verify runner, image, cloud API, and
infrastructure-tool versions against repository policy.

## Professional method
1. Identify target environment, release owner, SLO, dependencies, and rollback
   constraints.
2. Make builds deterministic and configuration externalized.
3. Scope CI identity and secrets to the minimum job/environment.
4. Build once and promote the same immutable artifact through environments.
5. Add readiness, telemetry, alarms, backup, and rollback evidence.
6. Validate in disposable/staging infrastructure before requesting production
   approval.

## Recommended architecture
Keep application config outside build artifacts; separate liveness from
readiness. Use least-privilege identities, immutable image digests, explicit
deployment gates, and backward-compatible schema rollouts. Ensure observability
has request IDs but excludes secret payloads.

## Code examples
Minimal CI should test before publishing; this example intentionally has no
deployment credentials or production step:

```yaml
name: validate
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v4
      - run: npm ci
      - run: npm test
      - run: npm run build
```

Use the repository's pinned action versions and package manager policy.

## Best practices
- Pin tools/images where policy requires and update through reviewed changes.
- Keep secrets in approved secret stores and never echo them in CI logs.
- Use readiness checks for traffic eligibility and liveness for process health.
- Test restore and rollback; a backup that was never restored is unverified.
- Make migrations compatible across rolling deploy versions.

## Anti-patterns
- Deploy-on-push to production without approval, staged verification, or rollback.
- Mutable `latest` artifacts with no traceable source revision.
- Overprivileged CI tokens and secrets available to untrusted pull requests.
- Destructive schema changes coupled to one application rollout.
- Claiming production readiness from a successful local container build.

## Error handling
Stop promotion on failed health checks, missing configuration, or migration
errors. Preserve logs and artifact identity while redacting secret values.
Provide a safe rollback/forward-fix decision path and state when it was not
exercised.

## Optimization
Right-size resources from observed CPU, memory, and request metrics. Use
autoscaling with bounded limits and graceful shutdown. Avoid extra services or
clusters without a measured reliability or cost need.

## Tests and validation
Validate workflow/IaC syntax, run build/test checks, inspect permissions and
secret exposure, and test health/rollback in a nonproduction target. Do not
claim a deployment or restore test unless one actually ran.

## Delivery checklist
- [ ] Build/test steps are reproducible
- [ ] CI identity and secrets are least-privilege
- [ ] Artifact, health, backup, and rollback are traceable
- [ ] Schema compatibility and failure recovery are considered
- [ ] No push, provisioning, or deployment happened without approval

## Official documentation
- [GitHub Actions security hardening](https://docs.github.com/actions/security-guides/security-hardening-for-github-actions)
- [Docker documentation](https://docs.docker.com/)
- [Kubernetes probes](https://kubernetes.io/docs/concepts/configuration/liveness-readiness-startup-probes/)
- [Google SRE workbook](https://sre.google/workbook/table-of-contents/)
