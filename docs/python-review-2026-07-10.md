# Multi-Facet Code Review: pREST Python Rewrite (Phases 0–5B)

**Review date:** 2026-07-10
**Scope:** All Python source, tests, docs, Docker, CI added since project start
**Reviewer:** Agent self-review (code-review-and-quality skill)

---

## 1. Architecture Boundaries (DDD)

### What's right

Dependency direction is mostly correct:

```
main.py → app.py → api/routes → domain + postgres → settings
                                    ↓
                           domain/identifiers (no deps)
                           domain/permissions → settings only
                           postgres/query_builder → domain/identifiers
                           postgres/executor → asyncpg (no internal deps)
                           postgres/pool → settings
```

- `domain/identifiers` is pure, zero-dependency — correct DDD leaf.
- `postgres/query_builder` depends only on `domain/identifiers` — clean.
- `postgres/executor` depends on nothing internal — correct infra leaf.
- `settings` has no dependency on other layers — correct.

### Issues

**Important — API layer imports infrastructure directly.** `crud.py` imports from `prest_py.postgres.executor` and `prest_py.postgres.query_builder` directly. Go solves this via the `adapters` port interfaces injected through `controllers.Deps`. The Python rewrite plan documents this boundary (`docs/python-rewrite-plan.md`): "Route functions should not assemble SQL directly." Currently they do.

This is acceptable for Phase 5 scaffolding but should be addressed before Phase 5C/5D. The Go `Deps` pattern should be ported — route handlers receive port interfaces, not concrete infrastructure.

**Optional — `domain/permissions` imports `settings.models`.** This couples domain logic to the settings schema. In Go, `TablePermissions` receives `config.AccessConf` as a value. For Python, extracting a `PermissionConfig` protocol/dataclass would decouple domain from settings, but this is premature until a third consumer appears (KISS/YAGNI).

---

## 2. Module Fit

### What's right

- `app.py` is a clean composition root — single `create_app` function, lifespan wiring, router registration. Matches Go's `app.New`.
- `api/routes/__init__.py` correctly registers health before CRUD to avoid route shadowing by `/{database}/{schema}/{table}`.
- `health.py` owns lifespan + pool creation — single responsibility for health + lifecycle.
- `pool.py` mirrors Go's `connection.Manager` contract faithfully: URI-keyed pools, lazy creation, `pg.single` enforcement.

### Issues

**Important — Lifespan lives in `health.py`.** `create_lifespan` is defined in `prest_py/api/routes/health.py` but called from `app.py`. The pool lifecycle is an application concern, not a health-route concern. In Go, this lives in `app.New` and `cmd/root.go`. Moving `create_lifespan` to `app.py` or a dedicated `prest_py/lifespan.py` would be cleaner.

**Nit — `build_uri_from_settings` uses `noqa: SLF001` to access private method.** `pool.py:build_uri_from_settings()` instantiates a `PoolManager` just to call `._uri_for()`. If this function is needed, `_uri_for` should be public or extracted as a standalone function.

---

## 3. Data Flow

### Select flow (GET /{database}/{schema}/{table})

```
Request → path params → alias validation → segment validation →
  query_params → field permissions → select_fields → select_sql →
  distinct → count → join → where → groupby → order → page →
  pool.get(database) → execute_query/execute_count → Response
```

**Correct:** matches Go's `CRUDHandler.Select` ordering step-by-step.

### Insert flow (POST /{database}/{schema}/{table})

```
Request → path params → alias validation → segment validation →
  body.json() → parse_insert_request → insert_sql →
  pool.get(database) → execute_insert (RETURNING row_to_json) → 201
```

**Correct:** matches Go's `CRUDHandler.Insert` + `fullInsert` behavior.

### Issues

**Critical — `execute_insert` appends `RETURNING` to unvalidated `table` string.** In `executor.py:42`:

```python
full_sql = f'{sql} RETURNING row_to_json("{table}")'
```

The `table` parameter comes from `request.path_params["table"]` which is validated by `is_safe_segment` (allows `[A-Za-z0-9_-]+`). This is safe because `is_safe_segment` blocks quotes, semicolons, and SQL metacharacters. But the validation happens in the route handler, not in the executor. The executor trusts its caller. If a future endpoint calls `execute_insert` without segment validation, this is an injection vector.

**Fix:** Either pass the already-quoted table reference, or re-validate inside `execute_insert`. The Go code extracts the table name from the SQL via regex and quotes it. The Python code should do the same or validate explicitly.

**Important — `except (TimeoutError, Exception)` in health.py is redundant.** `TimeoutError` is a subclass of `Exception`, so the tuple adds nothing. This is a code smell that suggests the author wasn't sure which exceptions to catch.

**Fix:** Use `except Exception:` or catch `asyncio.TimeoutError` explicitly if that's the intent.

---

## 4. Planning Drift

### Plan vs implementation alignment

| Plan phase | Status | Drift |
|---|---|---|
| Phase 0: Contract freeze | Done | Contract harness + CI + Go oracle baseline match plan |
| Phase 1: Python skeleton | Done | Matches plan. Docker port 23000 respects 20000-29999 policy |
| Phase 2: Config compatibility | Done | Initial slice matches plan. Not full parity yet (some Go config keys still missing) |
| Phase 3: Pool + registry | Done | Matches plan. `asyncpg` chosen over `sqlx` equivalent |
| Phase 4: SQL query builder | Done | Matches plan. All listed functions ported |
| Phase 5A: Select | Done | Matches plan |
| Phase 5B: Insert | Done | Matches plan |
| Phase 5C: Batch insert | Not started | No drift |
| Phase 5D: Update/delete | Not started | No drift |

### User-requested changes

1. **Port policy (20000-29999):** User asked after Phase 1. Applied to Docker compose and documented.
2. **Approved defaults:** Plugins → Python import-string, migrations → deferred, cache → in-memory TTL, code location → side-by-side. All recorded in plan and memory.

### Drift assessment

**No unplanned drift.** All phases delivered what the plan promised. The only architectural shortcut is the direct API→infrastructure dependency (section 1), which the plan explicitly says should not exist ("Route functions should not assemble SQL directly"). This is a known gap, not accidental drift.

---

## 5. Clean Code

### Ruff findings (27 errors)

**Important (fix before merge):**

1. `F401` — Unused imports:
   - `crud.py:14` — `InvalidIdentifier` imported but unused
   - `pool.py:3` — `Mapping` imported but unused

2. `F841` — `query_builder.py:300` — `pid = pid_ref[0]` assigned but never used

3. `F402` — `query_builder.py:465,628` — Loop variable `field` shadows imported `field` from `dataclasses`

4. `B007` — `query_builder.py:327` — Loop variable `item` unused, should be `_item`

5. `I001` — Import sorting in `pool.py` and `loader.py`

**Optional (lint preferences):**

6. `E501` — 10 lines over 100 chars in `crud.py` and `query_builder.py`
7. `S105` — Default password `"password"` in `AuthSettings` — matches Go defaults, acceptable
8. `S104` — `0.0.0.0` bind — matches Go, acceptable
9. `S608` — SQL injection warnings on `executor.py` and `query_builder.py` — false positives (identifiers validated upstream), but worth documenting with `noqa` comments

### Code smells

**Important — `_where_key_and_value` uses `pid_ref := [pid]` walrus assignment pattern.** In `where_by_request`, the placeholder counter is passed via a mutable list `pid_ref := [pid]`. This is a workaround for Python's lack of pointer semantics. The Go code uses `*int`. This works but is hard to read:

```python
clause, vls = _where_key_and_value(key, v, pid_ref := [pid])
pid = pid_ref[0]
```

**Fix:** Extract a small `PlaceholderCounter` class with `next()` method, or pass the counter position as return value tuple `(clause, values, next_pid)`.

**Important — Duplicated database validation in `crud.py`.** The same 8-line block appears in both `select_table` and `insert_table`:

```python
if settings.has_database_registry:
    if not settings.profile_by_alias(database):
        return JSONResponse(...)
    if settings.pg.single and database != settings.pg.database:
        return JSONResponse(...)
```

**Fix:** Extract to a shared `_validate_database_alias(settings, database)` helper.

**Important — Duplicated path-segment validation.** Same pattern:

```python
if not ident.is_safe_segment(database) or not ident.is_safe_segment(schema) or not ident.is_safe_segment(table):
    return JSONResponse(...)
```

**Fix:** Extract to `_validate_path_segments(database, schema, table)`.

**Nit — `_columns_by_request` has a late import.** `crud.py:210` imports `normalize_group_function` inside the function body. This was likely done to avoid circular imports but `query_builder` is already imported at module level.

**Nit — `_check_field` has a late import.** `permissions.py:87` does `import re` inside the function. Should be at module top.

---

## 6. Security

### What's right

- **SQL injection prevention is solid.** All identifiers validated via `ident.is_valid()` or `ident.is_safe_segment()` before any SQL string assembly. Values are always `$n` parameterized.
- **Pool URIs include SSL mode.** `pool.py` correctly passes `sslmode` in connection URIs.
- **No secrets in code.** Default passwords match Go but are documented as defaults, not hardcoded production secrets.
- **Contract tests prove Go parity.** 62 passed, 15 skipped against real Go oracle.

### Issues

**Critical — `execute_insert` builds SQL from unvalidated `table` parameter.** See section 3. The `table` string is interpolated directly into `RETURNING row_to_json("{table}")`. While currently safe because `is_safe_segment` blocks dangerous characters, the executor itself doesn't validate. Defense-in-depth: validate inside the executor.

**Important — Error messages echo raw exception text.** `crud.py` returns `{"error": str(e)}` from database exceptions. Go's `logsafe` package redacts sensitive info from error logs. Python should avoid leaking connection strings or internal paths in error responses.

**Fix:** Sanitize error messages or return generic messages with logged details.

**Important — `json_agg_type` interpolated into SQL without validation.** `executor.py:30`:

```python
wrapped = f"SELECT {json_agg_type}(s) FROM ({sql}) s"
```

`json_agg_type` comes from `settings.json_agg_type` which defaults to `"jsonb_agg"`. If a user configures an invalid value, it's injected into SQL. Go validates this via `getJSONAgg()` which only accepts `"json_agg"` or `"jsonb_agg"`.

**Fix:** Validate `json_agg_type` in the settings loader, not just in Go's `getJSONAgg`.

---

## Summary

### Verdict: **Approve with required changes before Phase 5C**

| Axis | Rating | Critical | Important | Nit |
|---|---|---|---|---|
| Architecture boundaries | Good | 0 | 1 | 1 |
| Module fit | Good | 0 | 1 | 1 |
| Data flow | Good | 1 | 1 | 0 |
| Planning alignment | Excellent | 0 | 0 | 0 |
| Clean code | Fair | 0 | 5 | 3 |
| Security | Good | 1 | 2 | 0 |
| **Total** | | **2** | **10** | **5** |

### Required before Phase 5C (Critical):

1. Validate `table` inside `execute_insert` (defense-in-depth against future callers)
2. Validate `json_agg_type` in settings loader (only `jsonb_agg` / `json_agg`)

### Required before Phase 5D (Important):

3. Remove unused imports (`InvalidIdentifier`, `Mapping`)
4. Fix `pid` unused variable in `_where_key_and_value`
5. Fix `field` variable shadowing imported `field` from dataclasses
6. Extract shared database/path validation helpers in `crud.py`
7. Fix `except (TimeoutError, Exception)` redundancy in `health.py`
8. Sanitize error messages in `crud.py` (avoid leaking DB internals)
9. Move `create_lifespan` out of `health.py` into `app.py` or `lifespan.py`

### Optional (Nit):

10. Fix import sorting
11. Move late imports to module top
12. Add `noqa: S608` comments on validated SQL builders
13. Replace `pid_ref := [pid]` walrus pattern with a counter class