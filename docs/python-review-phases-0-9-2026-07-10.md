# Multi-Facet Code Review: pREST Python Rewrite (Phases 0–9)

**Review date:** 2026-07-10  
**Scope:** Current Python implementation, tests, contract harness, config, Docker, CI, and rewrite plan  
**Verdict:** **Request changes — do not start Phase 10 yet**

## Executive summary

Structure is understandable and technology choices fit product. Source lint passes, 234 Python tests pass, lock resolves, Docker image builds, and dependency audit found no known vulnerabilities.

Current green tests do not prove a working API. No Python test or CI job exercises a successful PostgreSQL-backed request. Live review against seeded PostgreSQL confirmed every DB request fails before connecting because `PoolManager` passes an unsupported asyncpg argument. Further happy-path blockers and security-policy bypasses exist behind that failure.

### Severity totals

- **Critical:** 6
- **Important:** 9
- **Nit/cleanup:** 4

---

## Required findings

### Critical 1 — Pool creation is broken for every DB-backed endpoint

`prest_py/postgres/pool.py:123` passes `max_inactive_session_idle` to `asyncpg.create_pool`. asyncpg does not support that parameter; it forwards it to `connect()`, which raises:

```text
TypeError: connect() got an unexpected keyword argument 'max_inactive_session_idle'
```

Live seeded-Postgres smoke result:

```text
GET /_health                    -> 503
GET /prest-test/public/test     -> 400
```

Impact: health, readiness, catalog, CRUD, scripts, and auth cannot reach PostgreSQL.

Required change: map config to supported asyncpg pool options, then add successful pool + HTTP integration tests against real PostgreSQL.

### Critical 2 — Cache can bypass authentication and leak protected responses

`prest_py/api/middleware.py:49-56` returns a cache hit before FastAPI route dependencies run. `crud_protection` therefore never validates JWT or table access on a hit. Cache key contains URL only; it does not vary by authenticated identity or permission set.

Confirmed with current app: pre-populated protected URL + auth enabled + no token returned `200`, cached secret body, and `Cache-Server: prestd` instead of expected `401`.

Impact: unauthenticated and lower-privilege users can receive data cached from another user.

Required change: cache only after auth/access checks, or exclude protected responses. Include auth identity/authorization scope in key if user-specific responses remain cacheable. Add no-token, cross-user, whitelist, and per-field regression tests.

### Critical 3 — User-specific field permissions are ignored

Auth dependency extracts username at `prest_py/api/deps.py:113`. Select handler calls `fields_permissions(...)` at `prest_py/api/routes/crud.py:89` without passing that username.

For user-only access config, `fields_by_permission` falls back to `["*"]`; user can select fields outside their configured list.

Impact: column-level authorization leak.

Required change: pass authenticated username through select permission resolution. Test generated SELECT fields for two users with different field grants.

### Critical 4 — Configured global security policies are silently ignored

`prest_py/api/routes/__init__.py:15-25` protects only CRUD router with `crud_protection`. No implementation applies:

- `jwt.default` global JWT middleware
- `jwt.jwks` / `jwt.wellknownurl` verification
- `expose.enabled` restrictions

These settings exist in Pydantic models, and rewrite plan says they are implemented/preserved, but runtime ignores them.

Impact: deployments relying on default JWT or exposure config can expose endpoints they intended to protect.

Required change: implement policy at application boundary, fail startup for unsupported security config, or document an owner-approved divergence before release.

### Critical 5 — Core SQL references remain invalid after pool fix

Two independent references are invalid:

1. `prest_py/api/routes/auth.py:95` calls `table_reference("", ...)`, producing:

   ```sql
   SELECT * FROM ""."public"."prest_users" ...
   ```

   PostgreSQL rejects zero-length quoted identifier. `/auth` cannot authenticate.

2. `prest_py/postgres/query_builder.py:754` emits `"database"."schema"."table"` when no registry is configured. PostgreSQL does not support cross-database table references. Pool already connects to selected database, so default legacy CRUD SQL is invalid.

Impact: `/auth` and non-registry CRUD remain broken after Critical 1 is fixed.

Required change: centralize connection-scoped `schema.table` references and verify all CRUD/auth happy paths against seeded PostgreSQL.

### Critical 6 — Batch body keys enter SQL without identifier validation

`prest_py/postgres/query_builder.py:691-692` takes keys from request JSON and joins them directly into INSERT column SQL. Unlike single insert/update, batch keys are neither validated nor quoted. Malformed body shapes also raise uncaught `AttributeError`/`KeyError`.

Impact: untrusted input crosses SQL identifier boundary; malformed requests can become 500s. COPY and values paths have inconsistent identifier handling.

Required change: validate and quote every column, require non-empty list of objects with identical key sets, and return deterministic 400 errors. Add hostile-key and heterogeneous-record tests.

---

## Important findings

### Important 1 — Verification story does not exercise product behavior

`pytest` result is green because Python contract cases are skipped and endpoint tests stop before DB execution:

```text
234 passed, 77 skipped
```

`docker-compose-test.yml` has no Python default/multicluster/auth services. `.github/workflows/test-contract.yml` runs Go oracle only. `make test-contract-python` only invokes pytest and depends on manually supplied URLs.

No successful Python tests cover pool creation, SELECT, insert, batch, update, delete, catalog, auth, scripts, cache hit, or multi-cluster routing.

Required change: wire three Python services into compose/CI and run same contract cases against Go and Python. Treat unsupported cases as approved, linked `xfail`, not silent skips.

### Important 2 — Phase 7 feature claim is inaccurate

Plan says basic auth, default JWT, and JWKS behavior are implemented. Current login always reads JSON body; `auth.type = "basic"` is ignored. JWKS code does not exist. Auth query is broken as noted above. User metadata output also differs from Go when empty.

Required change: implement or explicitly defer each auth mode and update plan language.

### Important 3 — Array values are incompatible with asyncpg

`_format_array` at `prest_py/postgres/query_builder.py:373` converts Python lists to PostgreSQL array-literal strings. asyncpg array codecs require sized Python iterables, not a serialized string.

Confirmed:

```text
DataError: invalid input for query argument $1: '{a,b}'
(a sized iterable container expected (got type 'str'))
```

Affects INSERT, batch/COPY, UPDATE, and array filter values.

Required change: preserve Python lists for asyncpg or install explicit codecs. Add real DB array contract tests.

### Important 4 — Cache can grow without bound and cache operational routes

`ResponseCache` has no maximum entries or sweep. Expired unique keys remain forever unless same key is read again. Global middleware caches every successful GET when enabled and endpoint list is empty, including health/readiness, catalog, and scripts.

Impact: query-string/Host churn can cause memory growth; cached health can mask DB failure. Body accumulation at `middleware.py:64` uses repeated byte concatenation and buffers entire responses.

Required change: bound storage, evict expired entries, exclude health/readiness and protected/dynamic routes by default, preserve response metadata, and avoid quadratic body concatenation.

### Important 5 — Pool semantics are incomplete beyond broken argument

- Lazy creation at `pool.py:107-125` has no lock/single-flight; concurrent first requests can create and leak duplicate pools.
- URI builder does not safely encode credentials.
- Default `pg.url` is parsed then rebuilt, dropping query options other than `sslmode`.
- SSL cert/key/rootcert and connection timeout settings are ignored.
- `maxidleconn` mapping is undefined for asyncpg.

Required change: define asyncpg mapping, preserve DSN semantics, and test concurrent alias creation plus credential/SSL cases.

### Important 6 — Script compatibility is partial and traversal guard is weak

Parser is a regex subset, not Go `text/template`. Observable mismatches include:

- Starlette lowercases request header keys (`X-Application` becomes `x-application`), so existing `{{index .header "X-Application"}}` resolves empty.
- `isSet` renders `True`/`False`, not Go `true`/`false`.
- `split` performs an extra template-data lookup.
- No control structures or robust argument parsing.
- `resolve_script_path` uses string `startswith` at `postgres/scripts.py:195`, allowing sibling-prefix paths; it checks existence rather than regular file.

Required change: define supported template contract, port examples exactly, use resolved-path containment, and run existing scripts against PostgreSQL.

### Important 7 — Contract-required middleware behavior is absent

Current contract freeze includes `_renderer=xml`; Python has no renderer. CORS and context-path config are also modeled/planned but not applied. Catalog exposure behavior is absent. Catalog hides DB errors behind generic text, breaking frozen cases expecting `does not exist`.

Required change: either implement frozen behavior or record owner-approved divergences with tests/docs.

### Important 8 — DDD boundaries remain inverted

Routes directly assemble SQL and call asyncpg infrastructure. `catalog.py` and `scripts.py` import private helpers from `crud.py`. `domain.permissions` imports full settings models. Business/application flow is spread across 459-line CRUD and 312-line catalog route modules.

Required change: introduce narrow application use cases/ports before more features. Keep HTTP response mapping in routes; move query orchestration and policy decisions behind injected interfaces. Avoid speculative abstractions—one CRUD service, catalog service, auth service, and script service are enough.

### Important 9 — Config/build behavior is not production-compatible yet

- `load_settings(env={})` falls back to process env because it uses `env or os.environ`.
- Malformed TOML/Pydantic values abort startup despite planned lenient compatibility.
- Docker ignores `uv.lock` and runs unconstrained `pip install .`, so local and image dependency versions can differ.
- Python tests/lint are absent from CI.

Required change: distinguish `None` from empty env, define lenient errors, install from lock, and add Python CI gates.

---

## Five requested review facets

### 1. Architecture boundaries — DDD

**Rating: Needs changes**

Good:

- `domain.identifiers` is a clean leaf.
- Settings models/loading are separated.
- Pool/executor/query builder are distinct infrastructure modules.
- `app.py` is recognizable composition root.

Problems:

- API routes own application orchestration and SQL assembly.
- Route modules depend on concrete Postgres functions.
- Shared validation lives as private HTTP helper in CRUD route.
- Auth/access identity does not flow into field-policy evaluation.

### 2. Module architecture and fit

**Rating: Needs changes**

FastAPI + Pydantic + asyncpg fit dynamic PostgreSQL REST. Side-by-side rewrite and Go oracle strategy remain sound. Module fit breaks at global middleware ownership: cache, default JWT, exposure, rendering, CORS, and lifecycle policies need application-level composition with explicit ordering.

### 3. Product data flows

**Rating: Blocked**

- Config → app: partial; several modeled settings unused.
- App → pool: broken unsupported asyncpg argument.
- CRUD/catalog/scripts → DB: no successful verified path.
- Auth → DB: invalid SQL reference.
- JWT → table permission: works on cache miss for CRUD.
- JWT → field permission: username dropped.
- Cache → protected route: cache hit bypasses auth/access.
- Batch JSON → SQL: columns cross boundary unvalidated.

### 4. Planning alignment and drift

**Rating: Significant completion drift**

Aligned decisions:

- Python code remains side-by-side under `prest_py/`.
- FastAPI/Pydantic/asyncpg stack matches plan.
- External Docker port `23000` follows approved range.
- In-memory cache and Python-native plugin decision match approved defaults.

Drift:

- Phase 0 Python contract target and done checklist remain incomplete.
- Phase 1 promised typecheck and Python CI; neither exists.
- Phase 3 acceptance criteria are unmet.
- Phase 5 checkpoint requires CRUD contracts against both targets; unmet.
- Phase 6 exposure/multi-cluster acceptance is unmet.
- Phase 7 plan incorrectly says all auth features implemented.
- Phase 8 existing scripts are not executed in integration tests.
- Phase 9 acceptance calls for auth-sensitive behavior; tests do not test a cache hit.
- Immediate-next-steps section is stale after Phase 9.

### 5. Clean code and maintainability

**Rating: Mixed**

Good:

- Production source passes Ruff.
- Names and module-level docstrings are generally clear.
- Value placeholders are used across most query paths.
- `pip-audit` reports no known vulnerabilities.

Problems:

- Whole Python lint fails with 49 test errors.
- Test setup is duplicated across modules.
- No coverage tooling is installed.
- Route modules are large and repetitive.
- Dead/unused pool API exists (`current_database`, `set_database`, `pool_key_for_uri`, `build_uri_from_settings`, unused `_resolved`).
- Late imports recur in auth/scripts.
- Broad `dict`/`list` types and raw `Request.json()` lose Pydantic boundary validation.

---

## Verification run

| Check | Result |
|---|---|
| `uv run --extra dev pytest -q` | 234 passed, 77 skipped, 16 warnings |
| `uv run --extra dev ruff check prest_py` | Passed |
| `uv run --extra dev ruff check prest_py tests/python` | Failed: 49 test lint findings |
| `uv lock --check` | Passed |
| `python -m compileall -q prest_py` | Passed |
| Docker image build | Passed |
| Docker + seeded PostgreSQL smoke | Failed: pool kwarg error, health 503, SELECT 400 |
| Protected cache-hit probe | Failed security expectation: unauthenticated 200 |
| Direct auth SQL probe | Failed: zero-length quoted identifier |
| Direct asyncpg array probe | Failed: array string `DataError` |
| `pip-audit` | No known vulnerabilities |
| Go full local verification | Inconclusive: local DB absent; unit packages passed but command ended on missing Go `covdata` tool |

## Gate before Phase 10

Do not continue feature work until:

1. Critical 1–6 are fixed with regression tests.
2. Python default/multicluster/auth services run in compose.
3. Non-destructive Python contract suite passes against real PostgreSQL.
4. Security configs either work or fail startup explicitly.
5. Plan is corrected to distinguish implemented code from verified acceptance.

After fixes, rerun same five-facet review before Phase 10.
