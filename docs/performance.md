# Performance

## Status

The Python rewrite is in the same throughput ballpark as the Go reference on a simple read workload. Numbers below are a **local snapshot**, not a production guarantee. Capture your own with `scripts/run-baseline.sh`.

## Baseline snapshot (2026-07-12)

Environment: macOS, Docker Desktop, Postgres 16 in a container, single uvicorn worker, concurrency 20, 10s, GET `/{db}/public/test` (1000-row table).

| Server | RPS | p50 ms | p95 ms | p99 ms | Status |
|---|---|---|---|---|---|
| Go pREST (CGO_ENABLED=0, lib/pq) | 300.7 | 30.07 | 215.31 | 361.18 | 200 ×3007 |
| Python pREST (uvicorn, asyncpg) | 440.2 | 24.90 | 140.11 | 226.27 | 200 ×4402 |

Caveats:

- Single run per server; variance is high at this scale.
- macOS ephemeral-port limits cause connection churn above ~concurrency 50 — production Linux has a far larger ephemeral range.
- Go build here is `CGO_ENABLED=0` (no plugin system); production Go builds may differ.
- Python runs a single uvicorn worker; see tuning below for horizontal scaling.
- The workload is a trivial read. Write, batch, scripts, and auth paths have different profiles and are not measured here.

## Methodology

```sh
# Start a shared Postgres, build Go prestd, start both, run bench.py against each.
DURATION=10 CONCURRENCY=20 bash scripts/run-baseline.sh
```

`scripts/bench.py` is a self-contained async httpx load generator (no external benchmark binary). It warms up once, then runs N concurrent workers until the deadline, recording per-request latency and status counts.

For targeted runs against an already-running server:

```sh
uv run python scripts/bench.py --url http://127.0.0.1:23000/prest-test/public/test \
  --duration 20 --concurrency 50
```

## Tuning knobs

See `docs/tuning.md` for pool size, uvicorn workers, prepared statements, and serialization knobs.

## Targets

Performance targets (P95, throughput gap vs Go) are to be agreed with the owner before declaring the rewrite production-ready. See open checkpoint in `docs/python-rewrite-plan.md`.