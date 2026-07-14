# Python + Pydantic rewrite plan

This document plans a rewrite of pREST from Go to Python while preserving the current public contract: HTTP routes, PostgreSQL behavior, configuration compatibility, deployment shape, auth/access-control semantics, and production readiness.

The rewrite should not be a line-by-line port. Rebuild around Python architecture, then use the existing Go implementation as the reference oracle for contract tests.

## End goal

Deliver a Python implementation of pREST that provides the same core product promise:

- instant REST API over existing or new PostgreSQL databases
- dynamic table CRUD without ORM-owned schemas
- multi-database and multi-cluster routing
- auth, access control, catalog, script routes, cache, CLI, health/readiness
- production Docker/Kubernetes deployment
- high confidence through contract tests against current Go behavior

## Recommended target stack

- API: `FastAPI`
- Validation and config: `Pydantic v2`, `pydantic-settings`
- Database: direct `asyncpg` first; add SQLAlchemy Core only if it reduces complexity without hiding dynamic SQL behavior
- SQL construction: internal query builder, not ORM models
- Auth: `PyJWT` or `python-jose`
- CLI: `Typer`
- Tests: `pytest`, `pytest-asyncio`, `httpx`, Docker PostgreSQL
- Server: `uvicorn` or `gunicorn` with `uvicorn` workers
- Packaging: `pyproject.toml`

Port allocation constraint: internal Docker container ports may use normal service ports, but any externally published ports must use the `20000-29999` range because other local projects already use PostgreSQL, Redis, and FastAPI ports.

Reason: pREST is dynamic PostgreSQL REST, not model-first CRUD. SQL/query semantics are core domain behavior and should stay explicit.

## Current Go system map

Source areas to preserve or intentionally replace:

- `cmd/`: CLI, server start, migration commands
- `config/`: TOML/env config and database registry
- `app/`: composition root
- `router/`: route registration
- `controllers/`: auth, catalog, CRUD, script, health/readiness handlers
- `middlewares/`: auth, access control, exposure, cache, plugins
- `adapters/postgres/`: PostgreSQL pool, SQL builder, query executor, scanner, script execution
- `cache/`: response cache
- `plugins/`: Go `.so` plugin system
- `integration/`: HTTP contract tests

Core routes to preserve:

```http
POST /auth
GET /databases
GET /schemas
GET /tables
GET /{database}/{schema}
GET /show/{database}/{schema}/{table}
GET /_health
GET /_ready

GET    /{database}/{schema}/{table}
POST   /{database}/{schema}/{table}
POST   /batch/{database}/{schema}/{table}
DELETE /{database}/{schema}/{table}
PUT    /{database}/{schema}/{table}
PATCH  /{database}/{schema}/{table}

ANY /_QUERIES/{queriesLocation}/{script}
ANY /_QUERIES/{database}/{queriesLocation}/{script}
ANY /_PLUGIN/{file}/{func}
```

## Target Python architecture

Proposed package layout:

```text
prest_py/
  main.py                  # ASGI entry
  app.py                   # composition root

  settings/
    models.py              # Pydantic config models
    loader.py              # TOML/env loading

  api/
    routes/
      auth.py
      catalog.py
      crud.py
      scripts.py
      health.py
    middleware/
      auth.py
      access_control.py
      cache.py
      exposure.py

  domain/
    identifiers.py         # schema/table/database validation
    permissions.py
    query_params.py
    errors.py

  postgres/
    pool.py                # multi-database pool registry
    query_builder.py       # where/order/page/join/group/count/insert/update parsing
    executor.py            # execute queries and shape JSON responses
    catalog.py
    scripts.py

  cache/
    response_cache.py

  cli/
    main.py                # Typer commands
    migrations.py

  tests/
    contract/
    unit/
    integration/
```

Boundary rules:

- API layer owns HTTP parsing, response codes, and dependency injection.
- Domain layer owns identifier rules, permissions, query parameter semantics, and safe request interpretation.
- PostgreSQL infrastructure owns pool management, SQL generation, SQL execution, and result serialization.
- Settings layer owns config compatibility.
- Target architecture keeps SQL orchestration behind application use cases/ports. Phases 0–9 still contain route-level orchestration; owner accepted deferring the full DDD extraction to incremental prep alongside Phase 10 rather than mixing a big-bang refactor into the correctness/security repair batch.

## Phase 0: Contract freeze

Purpose: stop accidental behavior drift before rewriting.

Tasks:

1. Inventory current routes, query parameters, headers, status codes, and response bodies.
2. Convert existing Go integration cases into black-box contract specs.
3. Keep the Go service runnable in Docker as the reference oracle.
4. Build a Python test harness that can run the same HTTP tests against Go and Python targets.
5. Capture current quirks explicitly instead of silently correcting them.

Acceptance criteria:

- Contract test suite runs against the current Go service.
- Known behavior is documented, including edge cases and quirks.
- Python implementation cannot be accepted unless contract parity passes or divergence is approved.

Approval checkpoint:

- Decide whether Go `.so` plugin compatibility must be preserved. Native compatibility is not realistic in Python.

## Phase 1: Python skeleton

Initial M1 scaffold lives side-by-side with Go under `prest_py/`. Local Docker smoke service uses container port `3000` and publishes host port `23000` to respect the `20000-29999` external-port policy.

Run Python unit smoke tests:

```sh
uv run --extra dev pytest tests/python -q
```

Run local Python service:

```sh
docker compose -f docker-compose-python.yml up --build prest-python
curl http://127.0.0.1:23000/_health
```

Tasks:

1. Create Python package and FastAPI app factory.
2. Add `pyproject.toml`, lint, and test tooling. Static typecheck remains deferred until application ports reduce route-level dynamic request types.
3. Add Dockerfile and compose service alongside the Go service; publish external ports only in the `20000-29999` range.
4. Implement startup/shutdown lifecycle.
5. Implement initial `/_health` endpoint.
6. Add CI job for Python tests.

Acceptance criteria:

- `pytest` passes.
- `uvicorn prest_py.main:app` starts.
- Docker service boots.
- `GET /_health` returns expected status and shape.

## Phase 2: Config compatibility

Port behavior from `config/`.

Config compatibility exists in `prest_py/settings/loader.py` for defaults, `PREST_CONF`, core TOML sections, env overrides, `DATABASE_URL`, and multi-database registry env/TOML merging. Malformed TOML, invalid env casts, invalid optional fields, and invalid registry entries are logged and skipped without aborting startup; explicit `env={}` stays isolated from process environment.

Run config tests:

```sh
uv run --extra dev pytest tests/python/test_settings_loader.py -q
```

Tasks:

1. Model pREST config with Pydantic settings.
2. Support existing TOML shape.
3. Support `PREST_*` env overrides.
4. Support database registry env pairs:
   - `DATABASE_ALIAS_N`
   - `DATABASE_URL_N`
   - `PREST_DATABASE_ALIAS_N`
   - `PREST_DATABASE_URL_N`
5. Preserve `pg.single`, `access.tables`, `access.users`, `expose`, `cache`, `jwt`, `queries`, CORS, HTTPS, and logging fields where applicable.
6. Keep current lenient loading behavior: invalid optional config is logged and skipped when the Go implementation currently does that.

Acceptance criteria:

- Existing sample configs load unchanged.
- Invalid registry entries are skipped or rejected exactly as specified by contract tests.
- Unit tests mirror important cases from `config/*_test.go`.

## Phase 3: PostgreSQL pool and registry

Port connection behavior from `adapters/postgres/internal/connection` and registry behavior.

The pool implementation in `prest_py/postgres/pool.py` is keyed by URI, single-flight guarded during lazy creation, enforces `pg.single`, routes aliases, URL-encodes credentials, maps pool limits/connect timeout, supports certificate SSL contexts, and pings default + registered aliases. Real PostgreSQL contract services verify `/_health`, `/_ready`, default/legacy routing, and registry multi-cluster routing.

Run pool + health tests:

```sh
uv run --extra dev pytest tests/python/test_pool.py tests/python/test_health.py -q
```

Tasks:

1. Build async pool manager keyed by connection URI.
2. Support default database and alias-based routing.
3. Implement lazy pool creation per alias.
4. Implement `pg.single` enforcement.
5. Implement default DB ping and all-alias readiness ping.
6. Map existing pool limit config to asyncpg pool settings.

Acceptance criteria:

- Multiple aliases route to correct physical DB.
- Aliases sharing the same URI share a pool.
- `/_ready` fails if any registered DB fails.
- Connection budgeting behavior is documented.

## Phase 4: SQL query builder

Highest-risk phase. Port with narrow unit tests and SQL snapshot tests.

Initial query-builder slice exists in `prest_py/postgres/query_builder.py` and `prest_py/domain/identifiers.py`, covering identifier validation, where/order/page/distinct/count/join/groupby/returning/select-fields/insert/set/batch parsing, and SQL builders (select/insert/delete/update/table_reference). All values are parameterized with `$n` placeholders.

Run query-builder tests:

```sh
uv run --extra dev pytest tests/python/test_query_builder.py tests/python/test_identifiers.py -q
```

Tasks:

1. Port identifier validation from `internal/ident`.
2. Port path-segment validation.
3. Port request query parsing:
   - `WhereByRequest`
   - `OrderByRequest`
   - `PaginateIfPossible`
   - `DistinctClause`
   - `CountByRequest`
   - `JoinByRequest`
   - `GroupByClause`
   - `ParseInsertRequest`
   - `ParseBatchInsertRequest`
   - `SetByRequest`
4. Preserve placeholder/value separation.
5. Add tests for malformed operators, malformed identifiers, and mixed filter types.

Acceptance criteria:

- No unvalidated identifier can enter SQL.
- Values are parameterized.
- Generated SQL matches Go behavior or has approved documented divergence.
- Unit tests cover all public query operators.

## Phase 5: CRUD endpoints

Build vertical slices, each covering route, domain logic, SQL builder, executor, permissions, and tests.

### 5A: Select

Route: `GET /{database}/{schema}/{table}`

Initial select endpoint exists in `prest_py/api/routes/crud.py`, wiring query builder, field permissions (`prest_py/domain/permissions.py`), and async executor (`prest_py/postgres/executor.py`). Returns JSON via `jsonb_agg` wrapping matching Go contract.

Run select endpoint tests:

```sh
uv run --extra dev pytest tests/python/test_select_endpoint.py tests/python/test_permissions.py -q
```

Acceptance criteria:

- Field permissions apply.
- Filtering, ordering, pagination, grouping, joins, distinct, and count work.
- Cache writes only when enabled.
- Missing relation maps to same status/body as Go.

### 5B: Insert

Route: `POST /{database}/{schema}/{table}`

Insert endpoint exists in `prest_py/api/routes/crud.py`, wiring body parsing (`parse_insert_request`), SQL builder, and async executor with `RETURNING row_to_json("table")` matching Go `fullInsert` behavior. Returns `201` on success.

Acceptance criteria:

- JSON request body parsing matches Go behavior.
- Insert returns `201`.
- Returned body shape matches Go.

### 5C: Batch insert

Route: `POST /batch/{database}/{schema}/{table}`

Batch insert endpoint exists in `prest_py/api/routes/crud.py`. Supports both values path (default) and COPY path (via `Prest-Batch-Method: copy` header). Values path returns JSON array of inserted rows via `RETURNING row_to_json`. COPY path returns empty body with 201, matching Go contract.

Acceptance criteria:

- Values-based batch insert works.
- COPY-equivalent behavior is implemented with `asyncpg.copy_records_to_table` or deferred as approved divergence.
- `Prest-Batch-Method` behavior is covered.

### 5D: Update and delete

Routes:

- `PUT /{database}/{schema}/{table}`
- `PATCH /{database}/{schema}/{table}`
- `DELETE /{database}/{schema}/{table}`

All three endpoints exist in `prest_py/api/routes/crud.py`. DELETE parses WHERE and optional RETURNING. PUT/PATCH parse body for SET clause, then WHERE with continued placeholder numbering, then optional RETURNING. `execute_write` in executor handles both RETURNING (returns JSON array) and non-RETURNING (returns `{"rows_affected": N}`) paths.

Acceptance criteria:

- `WHERE` parsing matches Go.
- Rows-affected response shape matches Go.
- Table permissions apply.

Checkpoint:

- Non-destructive CRUD contract tests pass against both Go and Python targets. Destructive write cases remain opt-in via `--run-destructive-contract`.

## Phase 6: Catalog and table metadata

Port:

- `GET /databases`
- `GET /schemas`
- `GET /tables`
- `GET /{database}/{schema}`
- `GET /show/{database}/{schema}/{table}`

All five catalog endpoints exist in `prest_py/api/routes/catalog.py`. Databases and schemas support count via `_count`; listing routes support the frozen filter/order/page/distinct behavior. Schema-table values are parameterized, column metadata comes from `information_schema.columns`, and global exposure policy can deny database/schema/table listings with Go-compatible `401` responses.

Tasks:

1. Rebuild catalog SQL.
2. Apply exposure config.
3. Support filters, ordering, pagination, distinct, and count where current Go supports them.
4. Add multi-cluster catalog tests.

Acceptance criteria:

- Output JSON shape matches Go.
- Exposure-disabled endpoints return same status/body as Go.
- Multi-database alias behavior matches README semantics.

## Phase 7: Auth and access control

Port:

- `POST /auth` with body and HTTP Basic credential modes
- CRUD JWT middleware and global `jwt.default` middleware
- access table permissions
- user-specific field permissions
- whitelist matching
- explicit fail-closed handling for unsupported JWKS/discovery config

Implemented in `prest_py/api/routes/auth.py`, `prest_py/api/deps.py`, and `prest_py/api/middleware.py`. Local HMAC JWT uses PyJWT with configured algorithm; login emits HS256 with six-hour expiry. Bcrypt/MD5/SHA1 verification is supported. CRUD routes receive auth + access control; catalog/health remain public unless `jwt.default` is enabled outside debug mode.

JWKS and `.well-known` discovery are not implemented. App creation raises a configuration error when either is configured so the runtime cannot silently claim unenforced protection.

Security requirements:

- Empty JWT key fails closed.
- Unsupported verification material fails during app creation.
- Global policy executes before cache lookup.
- Secrets are not logged.
- Password verification matches configured Go behavior.

Acceptance criteria:

- Existing auth integration tests pass.
- Regression tests cover empty-key auth bypass prevention.
- User-specific table and field permissions work.

## Phase 8: SQL scripts

Port `_QUERIES` behavior.

Implemented in `prest_py/api/routes/scripts.py` and `prest_py/postgres/scripts.py`. The supported Go-style subset includes variables plus `sqlVal`, `sqlList`, `defaultOrValue`, `inFormat`, `limitOffset`, `ident`, `isSet`, `split`, and header `index`. Stateful SQL helpers generate `$n` placeholders; headers are case-insensitive; resolved paths use component-aware containment and regular-file checks. Existing GET/function/header/database-prefix examples pass against real PostgreSQL. Full Go `text/template` control-structure parity remains out of scope.

Tasks:

1. Resolve script files using current suffix rules:
   - `GET` -> `.read.sql`
   - `POST` -> `.write.sql`
   - `PUT`/`PATCH` -> `.update.sql`
   - `DELETE` -> `.delete.sql`
2. Replace Go template functions with Python equivalents.
3. Support request data injection and parameter collection.
4. Execute read/write routes with correct database routing.
5. Block path traversal.

Acceptance criteria:

- Existing script examples work.
- Script params stay parameterized.
- Missing script and invalid method errors match contract.

## Phase 9: Cache

Current Go implementation uses local BuntDB-backed caching. Python replacement uses bounded in-memory TTL cache (`prest_py/cache/response_cache.py`) and `CacheMiddleware` (`prest_py/api/middleware.py`) for eligible successful GET responses. Health/readiness are never cached. Authenticated CRUD is excluded from URL-keyed caching because field grants are user-specific, preventing cache hits from bypassing JWT/access checks. Redis remains an optional future backend.

Tasks:

1. Implement cache config model.
2. Add middleware for endpoint rules.
3. Cache eligible GET responses.
4. Respect auth whitelist and endpoint-specific cache rules.

Acceptance criteria:

- Cache tests cover enabled, disabled, endpoint-specific, and auth-sensitive behavior.
- Cache defaults are safe.

## Phase 10: Python-native plugins

Implemented in `prest_py/plugins/` and app composition. Go `.so` loading and `/_PLUGIN/{file}/{func}` compatibility are intentionally removed.

Configuration uses ordered import strings:

```toml
[plugins]
entries = ["my_package.prest_plugin:register"]
```

`PREST_PLUGIN_ENTRIES` accepts a JSON string array or comma-separated entries. Each zero-argument registration callable returns `PluginRegistration` containing FastAPI routers and/or middleware classes.

Runtime guarantees:

1. Plugins load once during app creation.
2. Malformed, duplicate, missing, non-callable, raising, or invalid registrations fail app creation with `PluginLoadError`.
3. Exact plugin routes register before broad dynamic catalog/CRUD patterns, matching Go plugin route reachability; exact path+method conflicts with core/earlier plugin routes fail startup.
4. Built-in runtime order stays XML renderer → global JWT/exposure → cache → configured plugin middleware → routes.
5. Plugin middleware executes in configuration order.
6. Empty plugin config preserves the frozen pREST contract.

Not implemented: `.so` ABI, compatibility route, hot reload, startup hooks, middleware constructor options, or plugin dependency graphs. See `docs/python-plugins.md`.

## Phase 11: CLI (migrations deferred to Go binary)

Port `cmd/` server/version behavior. Migration engine is NOT reimplemented.

**Decision (2026-07-12):** Keep Go `prestd` binary as the migration tool. Shared Postgres means same `public.schema_migrations` table and same `.up.sql`/`.down.sql` files work unchanged. DB schema changes rarely; rebuilding the migration mechanism is not a goal. Deployments run the Go binary (or a Go image) for `prestd migrate up/down/redo/reset/next/version`; the Python binary serves the API.

Tasks:

1. Create `prestd` Typer CLI.
2. Implement server command/default command (uvicorn entrypoint).
3. Implement `version`.
4. Document migration workflow: use Go `prestd migrate ...`; no Python `migrate` command shipped.
5. Optional: add a `prestd migrate` stub in the Python CLI that prints a pointer to the Go binary and exits non-zero, so users discover the workflow.

Acceptance criteria:

- Server and version CLI flags match Go where practical.
- Migration workflow documented; existing migration files unchanged.
- Docker entrypoint for the Python server remains straightforward; migrations run as a separate Go-binary step.

**Status (2026-07-12): COMPLETE.** Implemented `prest_py/cli.py` (Typer). `prestd` with no args or `prestd serve`-equivalent root callback starts uvicorn via `create_app(settings)` with `--host/--port/--config/--reload` overrides; `prestd version` reads package metadata; `migrate` group stubs `up/down/redo/reset/next/version` to exit code 2 with a pointer to the Go binary and `docs/python-migrations.md`. `[project.scripts] prestd` wired. Dockerfile.python CMD now `prestd --host 0.0.0.0 --port 3000`. 9 CLI tests added; 302 Python tests pass; Docker smoke green (health + in-container `prestd version`).

## Phase 12: Deployment, performance, release

Tasks:

1. Build production Docker image.
2. Add health/readiness probes.
3. Load test against Go baseline.
4. Tune asyncpg pool size and server worker count.
5. Tune prepared statement and response serialization behavior.
6. Generate migration guide from Go pREST to Python pREST.
7. Update install manifests and README references when the Python implementation becomes primary.

Acceptance criteria:

- P95 latency target is agreed and met.
- Throughput gap versus Go is measured and accepted or fixed.
- Docker/Kubernetes examples are updated.
- Release candidate has contract, integration, auth, and performance reports.

**Status (2026-07-12): implementation slices complete; performance targets pending human acceptance.** Hardened `Dockerfile.python` (multi-stage, non-root uid 1001, HEALTHCHECK, OCI labels). Added `install-manifests/kubernetes/deployment-python.yaml` (same probes, same env vars, resources block) and `docker-compose-prod-python.yml`. Added `scripts/bench.py` (async httpx load client) and `scripts/run-baseline.sh` (Go-vs-Python on shared Postgres). Baseline snapshot recorded in `docs/performance.md` (local, concurrency 20, 10s: Go 300.7 rps p95 215ms; Python 440.2 rps p95 140ms — Python competitive, no regression). Wrote `docs/tuning.md` (pool, uvicorn workers, prepared statements, cache, serialization, known limits) and `docs/migration-guide.md` (Go→Python cutover). Updated README + `install-manifests/README.md` to document the Python option. Gates: ruff clean, 302 Python tests pass, uv lock check, uv build, prod compose config, k8s yaml valid, hardened Docker smoke (non-root + health), 62 Python contracts pass/15 skip. Open: agree P95/throughput targets; decide whether to benchmark write/batch/auth before sign-off (proposed in `docs/performance.md`).

## Milestones

### M1: Runnable Python API foundation

Includes phases 1-3.

### M2: Read-only API parity

Includes select CRUD, catalog, and health/readiness.

### M3: Write API parity

Includes insert, update, delete, and batch insert.

### M4: Auth/security parity

Includes `/auth`, JWT, access control, field permissions, and security regressions.

### M5: Scripts/cache/CLI

Includes `_QUERIES`, cache, migrations, and CLI.

### M6: Production hardening

Includes performance, Docker, Kubernetes docs, migration guide, and release candidate.

## Risks and mitigations

| Risk | Impact | Mitigation |
|---|---:|---|
| SQL builder behavior drift | High | Contract tests plus SQL snapshot tests |
| SQL injection regression | High | Central identifier validator and parameterized values only |
| Go plugin incompatibility | Medium/High | Approved Python import-string replacement; document `.so` removal |
| Performance loss versus Go | Medium | Async stack and load tests from M2 onward |
| Config compatibility gaps | Medium | Golden config fixtures from current repo |
| Migration command incompatibility | Medium | Decide backend before implementation |
| Multi-DB pool bugs | High | Integration tests with `postgres` and `postgres-b` |

## Approved defaults

1. Plugins: replace Go `.so` plugins with a Python-native import-string plugin API.
2. Migrations: defer backend choice; preserve CLI command names first, then decide backend before Phase 11 implementation.
3. Cache: start with in-memory TTL cache; keep Redis as optional future production backend.
4. Code location: keep Python implementation side-by-side under `prest_py/` while Go remains the oracle.
5. Ports: internal Docker ports may use normal service ports; externally published ports must use `20000-29999`.

## Open decisions

1. What performance baseline is required for first production release?
2. Exact migration backend before Phase 11: custom-compatible, Alembic wrapper, or yoyo-migrations.

## Current verification snapshot

- Python unit suite: 302 passed.
- Python non-destructive contract target: 62 passed, 15 destructive cases skipped.
- Python destructive contract target: 77 passed.
- Python source + test Ruff gate: passed.
- Locked Docker runtime build: passed.
- Go remains the oracle; intentional differences require the divergence process in `docs/python-contract-freeze.md`.

## Immediate next steps

1. Resolve migration backend before Phase 11 implementation.
2. Implement the Typer CLI/server/version command slice.
3. Extract route orchestration behind narrow application ports incrementally during CLI/migration work; no big-bang DDD rewrite.
4. Agree performance targets before Phase 12 release work.
