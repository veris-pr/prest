# Tuning

Knobs for throughput, latency, and resource use in the Python pREST rewrite. Defaults are conservative for laptops/dev; raise for production after measuring.

## Connection pool (`pg.*`)

| Setting | Default | Meaning |
|---|---|---|
| `pg.maxopenconn` | 10 | asyncpg pool `max_size`. Upper bound on concurrent DB connections per alias. |
| `pg.maxidleconn` | 0 | asyncpg pool `min_size`. Idle connections kept open. Raise to avoid reconnect churn. |
| `pg.conntimeout` | 10 | Seconds to wait for a DB connection (pool acquire + connect). |

Per-alias overrides: `[[databases]]` entries accept `maxopenconn` / `maxidleconn`.

Budget: `replicas × aliases × pg.maxopenconn` connections per Postgres cluster. Use PgBouncer/RDS Proxy when many aliases are registered.

Tuning guidance:

- Set `pg.maxidleconn` to a small positive value (e.g. 2–5) in production so the pool keeps warm connections and avoids per-request reconnect cost.
- Set `pg.maxopenconn` to roughly `uvicorn_workers × concurrency` divided across aliases, capped by Postgres `max_connections`.
- asyncpg uses prepared statements by default via its internal statement cache (`statement_cache_size`, default 100). The pool does not override this. If you hit `cached plan must not change result type` errors after DDL, restart the pool (restart the server) or reduce `statement_cache_size` via a custom pool — not currently exposed as a setting (see Known limits).

## Server (uvicorn)

The `prestd` CLI starts a single uvicorn worker. For production, run multiple workers behind a reverse proxy or via uvicorn's `--workers`:

```sh
# Not yet exposed by the prestd CLI; run uvicorn directly for multi-worker:
uvicorn prest_py.app:create_app --factory --workers 4 --host 0.0.0.0 --port 3000
```

Each worker is a separate process with its own pool. Multiply pool budgets by worker count.

Workers vs. threads: asyncpg + uvloop is single-threaded async; prefer more workers over threads. One worker per CPU core is a reasonable start.

## Response cache (`cache.*`)

| Setting | Default | Meaning |
|---|---|---|
| `cache.enabled` | false | Enables in-memory TTL response cache for GET. |
| `cache.time` | 10 | Default TTL in minutes. |
| `cache.endpoints[]` | [] | Per-endpoint rules; matched paths override default TTL/enabled. |

Enable only for idempotent, low-change read endpoints. Cache hits skip plugin middleware and DB entirely.

## Serialization

Responses are JSON via FastAPI/Starlette (`ORJSONResponse` is not wired by default). For read-heavy workloads, switching to `orjson` lowers serialization CPU — not currently wired; see Known limits.

## Known limits (future knobs)

- `statement_cache_size` not exposed as a setting.
- `orjson` response class not wired.
- uvicorn `--workers` not exposed via `prestd` CLI (use `uvicorn ... --factory` directly).
- HTTP/2 not enabled.

## Measuring

```sh
DURATION=20 CONCURRENCY=50 bash scripts/run-baseline.sh
# or against a running server:
uv run python scripts/bench.py --url http://127.0.0.1:3000/prest-test/public/test --duration 20 --concurrency 50
```

Change one knob at a time; record RPS + p95 before/after in `docs/performance.md`.