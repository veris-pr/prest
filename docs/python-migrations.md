# Migrations

pREST Python **does not reimplement the migration engine.** Migrations are handled by the Go `prestd` binary, which remains the source of truth for schema changes.

## Why

The Python rewrite and the Go binary share the same Postgres database. The Go migration tool is already tested, ships today, and uses a `public.schema_migrations` table plus paired `NNN_name.up.sql` / `NNN_name.down.sql` files. Rebuilding that mechanism in Python would add risk and maintenance for a feature that changes rarely. The Python server focuses on serving the API; migrations stay on the proven Go tool.

## How to run migrations

Use the Go binary in your release/ops pipeline:

```sh
prestd migrate up    --path ./migrations --url "postgres://user:pass@host:5432/db?sslmode=disable"
prestd migrate down  --path ./migrations --url "postgres://user:pass@host:5432/db?sslmode=disable"
prestd migrate version
prestd migrate redo
prestd migrate reset
prestd migrate next +1
```

`--url` defaults to the driver URL built from `pg.*` config; `--path` defaults to `migrations.path` from config.

## What the Python CLI does

`prestd migrate ...` in the Python binary is a **stub**. It prints a pointer to this document and the Go command, then exits non-zero (code 2). It exists so operators discover the workflow quickly rather than seeing "command not found".

```sh
$ prestd migrate up
Migrations are handled by the Go pREST binary, not this Python server.
Install/Run: prestd migrate up --path <dir> --url <postgres-url>
See: docs/python-migrations.md
```

## Deployment shape

- **API server:** Python image, `prestd --host 0.0.0.0 --port 3000` (or `prestd serve`).
- **Migrations:** separate step using the Go `prestd` image/binary, run before rolling the API forward.

Both talk to the same Postgres. No schema drift, no duplicate engine.

## Unsupported in Python

- `prestd migrate auth up/down` (auth table create/drop) — use the Go binary.
- Migration file generation/autodiscovery — use the Go binary or write `.up.sql`/`.down.sql` by hand.