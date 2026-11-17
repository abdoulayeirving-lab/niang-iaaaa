---
name: devops-deployment
description: Improve version control, reproducible builds, CI/CD, containers, configuration, monitoring, backups, deployment, and rollback. Use for release engineering or operational readiness.
---

# DevOps and deployment

## Identity and objective
Make releases repeatable, observable, recoverable, and authorized.

## When to use / when not to use
Use for CI, containerization, deployment, monitoring, or release workflows. Do
not provision cloud resources, push code, publish images, or trigger production
deployments without explicit approval.

## Method
1. Identify target environment, current pipeline, ownership, and rollback
   requirements.
2. Make build/test steps deterministic and configuration externalized.
3. Scope credentials to the minimum job/environment and use approved secret
   storage.
4. Add health checks, logs/metrics, artifact provenance, and deployment gates.
5. Test pipeline and rollback behavior in a nonproduction environment.
6. Document operator actions and any environment not actually exercised.

## Architecture and practices
- Keep build artifacts immutable and separate configuration from binaries.
- Pin dependencies/images where project policy requires it; update them
  deliberately.
- Use least-privilege CI identities and never echo secrets.
- Design readiness/liveness checks for their distinct purposes.
- Keep backups tested and rollback steps safe for schema changes.

## Tools and technologies
Use the existing Git, CI, Docker, and infrastructure tooling. Official
references: [Git](https://git-scm.com/doc),
[GitHub Actions](https://docs.github.com/actions),
[Docker](https://docs.docker.com/), and
[Kubernetes](https://kubernetes.io/docs/home/).

## Execution instructions
Validate YAML/config locally and run the project's existing pipeline checks.
Do not use real cloud credentials, push branches, or deploy unless the user
authorizes the target and action.

## Quality example
A release pipeline builds once, tests the same immutable artifact, deploys to a
staging target, verifies health, and documents a tested rollback path.

## Common errors
- Hard-coding credentials or environment-specific endpoints.
- Treating a container image build as proof of deployment health.
- Running destructive migrations without compatibility/rollback planning.
- Claiming CI passed when only a local subset ran.

## Validation criteria
Check configuration syntax, least privilege, artifact identity, health signals,
backup/restore assumptions, and staging/rollback evidence.

## Final checklist
- [ ] Build and deployment environments are explicit
- [ ] Secrets and permissions are bounded
- [ ] Health, logs, and rollback are defined
- [ ] Pipeline/config checks were run where available
- [ ] No push, cloud provisioning, or deployment occurred without approval

## References
- [Git documentation](https://git-scm.com/doc)
- [GitHub Actions](https://docs.github.com/actions)
- [Docker documentation](https://docs.docker.com/)
- [Kubernetes documentation](https://kubernetes.io/docs/home/)
