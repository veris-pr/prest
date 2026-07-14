# Onboarding

Goal: take you from zero to a useful pREST contributor in one session.
Read top to bottom. Each step builds on the last. When you finish, you will
understand the architecture, the module boundaries, the data flow, and how to
make a change safely.

> **What pREST is:** a REST API over PostgreSQL with no ORM. It turns HTTP
> requests into parameterized SQL at runtime and returns rows as JSON. There
> are no table models in code — the schema *is* the database.

> **What the Python rewrite is:** `prest_py/` targets API contract parity with
> the Go `prestd` binary. Both talk to the same Postgres. Educational port;
> performance is not a goal.

---

## Documentation map (Diátaxis)

pREST docs follow [Diátaxis](https://diataxis.fr) — four kinds of docs for four
needs. Pick the one matching what you want right now.

| You want to... | Read | Docs |
|---|---|---|
| **learn** pREST from scratch, by doing | Tutorials | [`docs/tutorials/`](tutorials/README.md) |
| **do** a specific task | How-to guides | [`CONTRIBUTING.md`](../CONTRIBUTING.md), [`docs/migration-guide.md`](migration-guide.md), [`docs/python-plugins.md`](python-plugins.md), [`docs/tuning.md`](tuning.md) |
| look up a **fact** about the machinery | Reference | [`docs/reference.md`](reference.md) |
| **understand** why it is built this way | Explanation | [`docs/architecture.md`](architecture.md), [`docs/python-migrations.md`](python-migrations.md) |

**New here?** Do Tutorial 1 first, then follow the Steps below to become a
contributor.

---

## Step 0 — Run it (10 minutes)

You need Docker. No Go, no Postgres install required.

**Do [Tutorial 1 — Turn a table into a REST API](tutorials/getting-started.md).**
It is a hand-held lesson that starts pREST, seeds a table, and reads/writes it
over HTTP in ~10 minutes. Come back here when you finish — the rest of this
page explains what you just did.

Already ran it? Quick reference for running the server outside the tutorial:

```sh
uv sync --extra dev
PREST_PG_HOST=... PREST_PG_USER=... PREST_PG_PASS=... PREST_PG_DATABASE=... \
uv run prestd --host 0.0.0.0 --port 3000

# or a self-contained stack (auth off, for learning):
docker compose -f docker-compose-tutorial.yml up -d --build
```

Version check:

```sh
uv run prestd version
```

**Checkpoint:** you can hit `/_health` and get a response. Move on.

---

## Step 1 — Understand the product (read, no code)

Read these in order:

1. `README.md` — what pREST does, multi-database routing, access control.
2. `docs/migration-guide.md` section 1 (compatibility table) — what the Python
   port does and does **not** reimplement (JWKS/OpenID, `.so` plugins,
   migration engine).
3. This file, then `docs/architecture.md`.

**You should be able to answer:**
- What does `GET /prest-test/public/test` return? (rows of `test` as JSON)
- Why are there no table models in code? (pREST introspects the DB at runtime)
- What stays on the Go binary? (migrations)

---

## Step 2 — Understand the technology

pREST Python is a small stack. Know what each piece does and *why pREST uses it*.

| Tech | Role in pREST | Where |
|---|---|---|
| **FastAPI** | HTTP framework, routing, dependencies (auth/access control), OpenAPI | `prest_py/api/` |
| **Pydantic** | Config models (`Settings` + nested), validation | `prest_py/settings/models.py` |
| **asyncpg** | Async Postgres driver, connection pooling, prepared statements | `prest_py/postgres/pool.py`, `executor.py` |
| **uvicorn** | ASGI server | `prest_py/main.py`, `cli.py` |
| **Typer** | CLI (`prestd serve/version/migrate`) | `prest_py/cli.py` |
| **PyJWT** | HMAC JWT validation | `prest_py/api/deps.py`, `middleware.py` |
| **httpx** | Test client + load/parity scripts (dev only) | `tests/`, `scripts/` |

If a layer is unfamiliar, read its file once: `prest_py/app.py` (composition),
`prest_py/settings/models.py` (config shape), `prest_py/api/routes/crud.py`
(one real handler), `prest_py/postgres/query_builder.py` (SQL generation).

---

## Step 3 — Architecture (the mental model)

Read `docs/architecture.md` fully. The short version:

```
Client → Middleware → Route → Dependency(auth/access) → Executor → asyncpg → Postgres
                                                                      ↓
                                                                  JSON response
```

Three rules that explain most of the codebase:

1. **Dependency direction is inward only.** `domain` and `settings` are inner
   (no infra). `postgres` depends on them. `api` depends on `postgres`.
   `app.py` wires everything. Routes never import `app`.
2. **No SQL is built by string-concatenating user input.** Identifiers are
   validated (`domain/identifiers.py`); values are `$n` parameters
   (`query_builder.py` `Query` dataclass).
3. **Fail closed on security misconfig.** Empty JWT key + `jwt.default` on, or
   JWKS set → app creation raises. The runtime refuses to pretend it protects.

**Checkpoint:** draw the request lifecycle for `GET /db/public/tbl?x=1` from
memory. If you can, you understand the architecture. If not, re-read
`docs/architecture.md` "Request lifecycle".

---

## Step 4 — Module boundaries (where things live)

Memorize this map. It is the answer to "where do I edit?"

| Package | Owns |
|---|---|
| `settings/` | config schema + loader |
| `domain/` | pure rules — identifier validation, permission matching |
| `postgres/` | pool, SQL builder, executor, script runner |
| `api/routes/` | HTTP handlers (health, auth, catalog, crud, scripts) |
| `api/deps.py` | request-time auth + access control (CRUD only) |
| `api/middleware.py` | XML renderer, global JWT/exposure, cache |
| `cache/` | in-memory TTL response cache |
| `plugins/` | import-string plugin contract + loader |
| `app.py` | composition root |
| `cli.py` | Typer CLI |
| `main.py` | uvicorn import target |

The full "where things go" cheat sheet is at the bottom of
`docs/architecture.md`.

**Exercise:** open `prest_py/api/routes/__init__.py`. Why is `health` registered
before CRUD, and `catalog` before `crud`? (Answer in the file's comments:
broad `/{database}/{schema}/{table}` would eat `/_health` and `/{db}/{schema}`
if registered first.)

---

## Step 5 — Data flow (trace a real request)

Trace these two flows end to end by reading the files named:

**Flow A — a CRUD read with a filter:**

1. `GET /prest-test/public/test?name=alice` hits FastAPI.
2. `prest_py/api/middleware.py` `GlobalPolicyMiddleware` (JWT/exposure) →
   `CacheMiddleware` (no hit) → route.
3. `prest_py/api/deps.py` `crud_protection`: `auth_dependency` (JWT if
   `auth.enabled`) → `access_control_dependency`
   (`domain/permissions.py` `table_permissions` for `read`).
4. `prest_py/api/routes/crud.py` handler calls
   `prest_py/postgres/query_builder.py` to build
   `SELECT ... WHERE name = $1 ...`.
5. `prest_py/postgres/executor.py` acquires a connection from
   `prest_py/postgres/pool.py`, runs the query wrapped in `jsonb_agg`, coerces
   types.
6. Response → `CacheMiddleware` caches the 200 (if enabled+eligible) →
   `XMLRendererMiddleware` → client.

**Flow B — config to a running server:**

1. `cli.py` `_run_server` calls `settings/loader.py` `load_settings`
   (defaults < `prest.toml` < `PREST_*` env).
2. `app.py` `create_app(settings)`: validates security config, loads plugins,
   builds the FastAPI app, adds middleware (in reverse for runtime order),
   includes plugin routes then core routes, builds the middleware stack early.
3. `lifespan` (in `app.py`) creates `PoolManager`, opens the default pool,
   pings, yields, closes on shutdown.

**Checkpoint:** where does `request.state.user_info` get set, and which routes
see it? (Answer: `api/deps.py` `auth_dependency`, only CRUD routes via
`crud_protection`. Global JWT does **not** set it.)

---

## Step 6 — Make a small change (your first contribution)

Follow `CONTRIBUTING.md` for the full workflow. The 5-minute version:

```sh
uv sync --extra dev
uv run ruff check prest_py tests/python   # lint
uv run pytest tests/python -q              # unit tests (should be green)
make test-contract-python                  # HTTP contract vs Go (docker)
```

Pick a trivial first task: add a new query param, extend a route's response
field, or add a unit test for an uncovered branch in `query_builder.py`.

Before you start a non-trivial change, read `docs/architecture.md`
"Where things go" and add/adjust a test in the right place:

- Pure logic → `tests/python/` unit test.
- HTTP behavior that must match Go → `tests/contract/` contract test
  (run with `make test-contract-python`; use `--run-destructive-contract` for
  write cases).

---

## Glossary

| Term | Meaning |
|---|---|
| **alias** | URL-visible database name; may differ from the physical DB name |
| **registry** | `[[databases]]` / `DATABASE_ALIAS_N`+`DATABASE_URL_N` multi-cluster config |
| **`pg.single`** | when true + registry active, only the default alias is accepted |
| **access tables** | `access.tables` per-table permission rules (`read`/`write`/`delete`) |
| **`_QUERIES`** | saved SQL script files served as endpoints (`/_QUERIES/{db}/{loc}/{script}`) |
| **endpoint rules** | per-path cache config (`cache.endpoints[]`) |
| **crud_protection** | combined auth + access-control dependency on CRUD routes |
| **whitelist** | `jwt.whitelist` regex patterns that skip JWT validation |
| **contract** | frozen HTTP behavior tested against the Go binary (`tests/contract/`) |

---

## You are ready when you can

- [ ] Run the server and get a JSON response from a table.
- [ ] Draw the request lifecycle from memory.
- [ ] Name which package owns SQL generation, which owns auth, which owns config.
- [ ] Explain why identifiers are validated and values are parameterized.
- [ ] Run lint + unit + contract gates and read a failure.
- [ ] Add a unit test and a contract test in the right files.

Next: `CONTRIBUTING.md` for conventions, PR checklist, and "how to add X"
recipes. For facts, `docs/reference.md`. Welcome aboard.