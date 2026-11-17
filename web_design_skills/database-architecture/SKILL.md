---
name: database-architecture
description: Model and evolve relational or document data safely, including schema design, indexes, transactions, migrations, backup, and query performance. Use when a feature changes persistence or data access.
---

# Database architecture

## Identity and objective
Keep persisted data correct, understandable, secure, and evolvable as the
application changes.

## When to use / when not to use
Use for schema, query, transaction, migration, or persistence decisions. Do not
select a new production database, run destructive migrations, or create
production data without approval.

## Method
1. Identify the current database, schema, version, migration tool, and data
   ownership.
2. Model entities, constraints, cardinality, lifecycle, and deletion policy.
3. Define indexes from expected query patterns, not speculation.
4. Design backward-compatible migrations and a rollback/recovery plan.
5. Use transactions around related writes and parameterized queries.
6. Test constraints, migration from the current schema, and representative
   queries with safe local data.

## Architecture and practices
- Encode invariants with appropriate primary/foreign keys, unique constraints,
  and checks.
- Avoid storing derived data unless consistency is explicitly managed.
- Use explicit transaction boundaries and isolation appropriate to the
  operation.
- Limit data returned and avoid N+1 query patterns.
- Protect backups and keep secrets out of schema fixtures and logs.

## Tools and technologies
Reuse the current database and migration tooling. Official references:
[PostgreSQL](https://www.postgresql.org/docs/),
[SQLite](https://www.sqlite.org/docs.html),
[MySQL](https://dev.mysql.com/doc/), and
[MongoDB](https://www.mongodb.com/docs/).

## Execution instructions
Do not modify a production database. Add a migration through the project's
existing tool, test it on a disposable/local database, and report any manual
operator step. Never put sample or seed data into migrations unless explicitly
requested.

## Quality example
A uniqueness rule is enforced by the database and application; a migration
adds the constraint only after checking existing data and has a documented
recovery path.

## Common errors
- Omitting constraints and relying only on application validation.
- Adding indexes without understanding write/storage cost.
- Deleting or renaming columns in a single deploy when old code still uses
  them.
- Testing migrations only on an empty database.

## Validation criteria
Verify migration up/down or recovery behavior where supported, constraints,
transaction rollback, query plans for critical paths, and backup assumptions.

## Final checklist
- [ ] Data model and ownership are documented
- [ ] Constraints and transactions enforce invariants
- [ ] Migration is safe for existing data and reversible/recoverable
- [ ] Queries are bounded and use appropriate indexes
- [ ] No production data was touched without explicit approval

## References
- [PostgreSQL documentation](https://www.postgresql.org/docs/)
- [SQLite documentation](https://www.sqlite.org/docs.html)
- [MySQL documentation](https://dev.mysql.com/doc/)
- [MongoDB documentation](https://www.mongodb.com/docs/)
