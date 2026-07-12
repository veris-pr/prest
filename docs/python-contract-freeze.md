# Python rewrite contract freeze

This document defines the Phase 0 contract-freeze target for the Python + Pydantic rewrite. The current Go implementation is the oracle until an intentional divergence is approved.

Goal: capture observable behavior before Python implementation starts, then run the same black-box tests against both services.

## Contract sources

Primary sources:

- Route registration: `router/router.go`
- HTTP integration tests:
  - `integration/controllers/catalog_test.go`
  - `integration/controllers/crud_test.go`
  - `integration/controllers/scripts_test.go`
  - `integration/controllers/auth_test.go`
  - `integration/controllers/health_test.go`
  - `integration/controllers/ready_test.go`
  - `integration/controllers/multicluster_test.go`
- Query-builder behavior tests:
  - `integration/adapters/postgres/postgres_test.go`
  - `adapters/postgres/postgres_test.go`
- Script lookup/execution tests:
  - `integration/adapters/postgres/queries_test.go`
- Public docs: `README.md`
- Seed data and server configs:
  - `testdata/db-init.sh`
  - `testdata/prest.toml`
  - `testdata/prest_multicluster.toml`
  - `docker-compose-test.yml`

## Test target model

Contract tests should run against a base URL, not imported app internals.

Port constraint: internal Docker service ports are fine, but any host-published ports used for local contract runs must be in the `20000-29999` range because other local projects already use PostgreSQL, Redis, and FastAPI ports.

Required targets:

- Go default server: `PREST_TEST_URL`
- Go multi-cluster server: `PREST_MULTICLUSTER_TEST_URL`
- Go auth server: `PREST_AUTH_TEST_URL`
- Python default server: `PY_PREST_TEST_URL` or same test variable under a target selector
- Python multi-cluster server
- Python auth server

Recommended contract-test command shape:

```sh
make test-contract-go
make test-contract-python
```

Direct pytest commands are also supported:

```sh
pytest tests/contract --target=go
pytest tests/contract --target=python
```

Every contract case should record:

- method
- path
- headers
- request body
- expected status
- expected response body fragments or exact JSON where stable
- target server kind: default, multi-cluster, auth
- source Go test reference

## Route inventory

### Auth

| Method | Path | Enabled when | Expected behavior |
|---|---|---|---|
| `POST` | `/auth` | `auth.enabled = true` | Returns token or `401` for missing/invalid credentials |
| `GET` | `/auth` | `auth.enabled = true` | `405 Method Not Allowed` |
| `POST` | `/auth` | `auth.enabled = false` | `404 Not Found` |

Sources: `router/router.go`, `integration/controllers/auth_test.go`, `controllers/auth_test.go`.

### Catalog

| Method | Path | Expected behavior |
|---|---|---|
| `GET` | `/databases` | List databases; supports filters/order/page/count/distinct |
| `GET` | `/schemas` | List schemas; supports filters/order/page/count/distinct |
| `GET` | `/tables` | List tables; supports filters/order/page/count/distinct |
| `GET` | `/{database}/{schema}` | List tables in schema for selected database/alias |
| `GET` | `/show/{database}/{schema}/{table}` | Show table metadata |

Sources: `integration/controllers/catalog_test.go`, `integration/controllers/crud_test.go`.

### CRUD

| Method | Path | Expected behavior |
|---|---|---|
| `GET` | `/{database}/{schema}/{table}` | Select rows/views with query params and field permissions |
| `POST` | `/{database}/{schema}/{table}` | Insert one row; returns `201` |
| `POST` | `/batch/{database}/{schema}/{table}` | Insert multiple rows; optional `Prest-Batch-Method: copy` |
| `DELETE` | `/{database}/{schema}/{table}` | Delete rows, optional filters |
| `PUT` | `/{database}/{schema}/{table}` | Update rows, optional filters and returning fields |
| `PATCH` | `/{database}/{schema}/{table}` | Same update behavior as `PUT` |

Sources: `integration/controllers/crud_test.go`, `controllers/crud_test.go`.

### Scripts

| Method | Path | Expected behavior |
|---|---|---|
| any CRUD method | `/_QUERIES/{queriesLocation}/{script}` | Execute SQL template against default database |
| any CRUD method | `/_QUERIES/{database}/{queriesLocation}/{script}` | Execute SQL template against selected database/alias |

Script suffix mapping:

| Method | Suffix |
|---|---|
| `GET` | `.read.sql` |
| `POST` | `.write.sql` |
| `PUT` | `.update.sql` |
| `PATCH` | `.update.sql` |
| `DELETE` | `.delete.sql` |

Sources: `controllers/script.go`, `adapters/postgres/queries.go`, `integration/controllers/scripts_test.go`.

### Health/readiness

| Method | Path | Expected behavior |
|---|---|---|
| `GET` | `/_health` | Ping default DB; `200` when alive |
| `GET` | `/_ready` | Ping default DB and every registered alias; `200` when all alive |

Sources: `README.md`, `integration/controllers/health_test.go`, `integration/controllers/ready_test.go`.

### Plugins

| Method | Path | Expected behavior |
|---|---|---|
| any | `/_PLUGIN/{file}/{func}` | Invoke Go `.so` plugin handler on non-Windows builds |

This is a compatibility decision point. Native Go `.so` plugin support is not realistic in Python.

Sources: `router/router.go`, `plugins/plugins.go`, `integration/plugins/*`.

## Query parameter contract

### Reserved params

| Param | Applies to | Behavior |
|---|---|---|
| `_select` | table/view select | comma-separated fields or aggregate expressions; `*` allowed |
| `_count` | select/catalog | count selected field or `*` |
| `_count_first` | select count | return single count object instead of list when set |
| `_order` | select/catalog | comma-separated fields; leading `-` means descending |
| `_page` | select/catalog | page number; invalid integer -> `400` |
| `_page_size` | select/catalog | page size; invalid integer -> `400` |
| `_distinct` | select/catalog | when `true`, rewrites `SELECT` to `SELECT DISTINCT`; empty value currently tolerated in some paths |
| `_join` | select | join expression `type:table:left:operator:right` |
| `_groupby` | select | group fields, optional having expression |
| `_returning` | update/insert builder | returning fields; supports `*` and repeated params |
| `_renderer` | response rendering | `xml` converts supported JSON responses to XML |

### Filter params

Any non-reserved query parameter is interpreted as a filter field. Field names must pass identifier validation. Values may include operators.

Known operators must be copied from current query builder tests and implementation. Contract tests should cover at least:

- equality forms used by integration tests: `field=$eq.value`, `field=value`
- comparison: `$gt`, `$gte`, `$lt`, `$lte`
- join operators as used by `_join`
- invalid operator behavior
- invalid identifier behavior

### Identifier validation

Contract-critical cases:

- invalid database like `/0prest-test/...` -> `400`
- invalid schema like `/prest-test/0public/...` -> often DB relation error mapped to `404` for CRUD writes
- invalid table like `/prest-test/public/0test` -> often `404` for CRUD writes
- invalid configured alias like `/invalid/public/test` -> `400`
- invalid query field like `?0name=$eq.test` -> `400`
- invalid order field like `?_order=0name` -> `400`

Exact status mapping must be tested per endpoint because current behavior is not uniform.

## Response body contract

Use exact body assertions only for stable cases. Use JSON comparison where ordering is stable. Use body-substring assertions for DB/version-specific errors.

Known stable examples from current integration tests:

- `GET /prest-test/public/testarray` returns:

```json
[{"id": 100, "data": ["Gohan", "Goten"]}]
```

- `GET /prest-test/public/Reply` returns:

```json
[{"id": 1, "name": "prest tester"}]
```

- `GET /prest-test/public/view_test?_count=player` returns list form:

```json
[{"count": 1}]
```

- `GET /prest-test/public/view_test?_count=player&_count_first=true` returns object form:

```json
{"count":1}
```

- `GET /schemas?_count=*&_renderer=xml` returns:

```xml
<objects><object><count>4</count></object></objects>
```

## Status-code matrix to freeze

### Catalog

| Case | Expected status |
|---|---:|
| valid `/databases`, `/schemas`, `/tables` | `200` |
| valid filter/order/page/count/distinct | `200` |
| invalid query identifier | `400` |
| invalid order identifier | `400` |
| invalid page number | `400` |
| non-existent catalog column | `400` |
| empty `_distinct` on `/databases` | `200` currently |

### Select

| Case | Expected status |
|---|---:|
| valid table or view select | `200` |
| valid `_count`, `_select`, `_order`, `_page`, `_join`, `_groupby` | `200` |
| invalid `_join` shape/type/operator/field | `400` |
| invalid filter identifier | `400` |
| invalid `_order` field | `400` |
| invalid `_page` | `400` |
| invalid `_count` field | `400` |
| invalid configured database/alias | `400` |

### Insert/batch/update/delete

| Case | Expected status |
|---|---:|
| valid insert | `201` |
| valid batch insert | `201` |
| valid batch copy | `201` with empty body in current tests |
| valid update/delete | `200` |
| invalid database identifier | `400` |
| invalid schema/table identifier in CRUD write path | `404` in current integration tests |
| invalid body | `400` |
| invalid where identifier | `400` |
| invalid configured database/alias | `400` |

### Scripts

| Case | Expected status |
|---|---:|
| existing script, valid SQL | `200` |
| missing folder | `400` |
| missing script | `400` |
| invalid SQL execution | `400` |
| debug disabled query error | generic body: `could not execute sql, check your prest logs` |

### Auth

| Case | Expected status |
|---|---:|
| auth disabled, `POST /auth` | `404` |
| auth enabled, `GET /auth` | `405` |
| auth enabled, missing credentials `POST /auth` | `401` |

## Multi-database contract

Routing rule:

- CRUD/catalog/script routes use the first URL path segment as database selector.
- Without registry, path segment is physical Postgres database name.
- With registry, path segment is registered alias.
- `pg.single = true` rejects non-default database/alias.
- Readiness pings default and all registered aliases.

Must test:

- default `prest-test`
- secondary DB from `helpers.Databases()` / `prest_multicluster.toml`
- unregistered alias -> `400`
- aliases with separate physical databases
- optional script route with database prefix

## Header contract

| Header | Endpoint | Behavior |
|---|---|---|
| `Authorization: Bearer <token>` | protected CRUD/script paths | required when auth middleware enabled unless whitelisted |
| `Prest-Batch-Method: copy` | `/batch/{database}/{schema}/{table}` | use COPY-style batch insert path |

Add CORS and content-type assertions after Python skeleton exists if current behavior matters to clients.

## Contract test implementation plan

### Step 1: Extract case tables

Create Python data-driven cases from existing Go integration tables:

- `catalog_cases.py`
- `crud_select_cases.py`
- `crud_write_cases.py`
- `script_cases.py`
- `auth_cases.py`
- `health_cases.py`
- `multicluster_cases.py`

Each case should include `source_ref`, e.g. `integration/controllers/crud_test.go:TestSelectFromTables`.

### Step 2: Add target fixture

The fixture resolves base URLs by target and server kind:

```text
target=go, server=default       -> PREST_TEST_URL
target=go, server=multicluster  -> PREST_MULTICLUSTER_TEST_URL
target=go, server=auth          -> PREST_AUTH_TEST_URL
target=python, server=default   -> PY_PREST_TEST_URL
target=python, server=multicluster -> PY_PREST_MULTICLUSTER_TEST_URL
target=python, server=auth      -> PY_PREST_AUTH_TEST_URL
```

### Step 3: Assert response safely

Use layered assertions:

1. status code exact match
2. body exact match only when stable
3. JSON semantic match where stable
4. body fragment match for DB/version-specific errors
5. no assertion for unstable body until explicitly frozen

### Step 4: Run Go oracle in CI

Before Python code exists, CI should prove contract tests pass against Go services from `docker-compose-test.yml`.

Use:

```sh
make test-contract-go
```

CI workflow: `.github/workflows/test-contract.yml` runs `make test-contract-go CONTRACT_ARGS="-q"` for contract-related changes and on manual dispatch.

### Step 5: Add Python target

After M1 skeleton exists, run same cases against Python. Mark expected unsupported cases as `xfail` only with linked open decision.

## Intentional divergence process

Any behavior change from Go must be recorded before implementation merges:

1. Name old Go behavior.
2. Explain why Python behavior differs.
3. Identify affected clients/tests/docs.
4. Get owner approval.
5. Add test asserting new behavior.
6. Update `docs/python-rewrite-plan.md` and this document.

Approved divergence/default candidates:

- Go `.so` plugin route will be replaced by a Python-native import-string plugin API.
- Cache starts as in-memory TTL; Redis remains optional later.
- Migration backend is deferred; CLI command names should be preserved first.

Likely remaining divergence candidates:

- exact PostgreSQL driver error text
- performance tuning defaults

## Current contract baselines

Run the non-destructive targets:

```sh
make test-contract-go CONTRACT_ARGS="-q"
make test-contract-python CONTRACT_ARGS="-q"
```

Latest results:

```text
Go oracle:                  62 passed, 15 skipped
Python non-destructive:     62 passed, 15 skipped
Python destructive opt-in:  77 passed
```

Skipped cases are destructive write/script mutations gated behind `--run-destructive-contract`. Python default, multi-cluster, and auth services are defined in `docker-compose-test.yml`; CI runs both targets from `.github/workflows/test-contract.yml`.

## Phase 0 done criteria

- [x] Contract test harness exists.
- [x] Go oracle tests pass in Docker.
- [x] Route/status matrix above is represented as executable tests.
- [x] Query-builder SQL snapshot tests exist for high-risk params.
- [x] Plugin/cache decisions are resolved; migration backend remains an explicit Phase 11 blocker.
- [x] Python target runs the same non-destructive suite in Docker/CI.
