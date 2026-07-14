# Python rewrite Phase 12 review — 2026-07-12

## Scope

Reviewed deployment, performance, and release-readiness slices:

- `Dockerfile.python` (hardened)
- `install-manifests/kubernetes/deployment-python.yaml`
- `docker-compose-prod-python.yml`
- `scripts/bench.py`, `scripts/run-baseline.sh`
- `docs/performance.md`, `docs/tuning.md`, `docs/migration-guide.md`, `docs/python-migrations.md`
- `README.md`, `install-manifests/README.md`
- `docs/python-rewrite-plan.md` Phase 12 update

## Verdict

Implementation slices complete. **Phase 12 not yet fully closed**: performance targets (P95, throughput gap) and the "benchmark write/batch/auth before sign-off" decision are pending human acceptance. No code blocker remains.

## Facet results

### 1. Architecture boundaries — pass

Deployment manifests, docs, and scripts sit at the infrastructure boundary; no domain/application code touched. `scripts/bench.py` is a client-only tool with no import of `prest_py` internals. Docs reference settings keys rather than redeclaring them.

### 2. Architecture fit — pass

Hardened image is multi-stage (builder + runtime), non-root (uid 1001), with HEALTHCHECK and OCI labels. k8s manifest mirrors Go probes (`/_health`, `/_ready`) and env vars; adds resources + JWT secret. Prod compose mirrors the Go prod compose with the Python image and 20000-29999 host ports. Migration workflow is explicitly separated (Go binary), matching the Option 5 decision.

### 3. Data flow — pass

Baseline harness: shared Postgres → seeded table → Go prestd + Python prestd (same env) → `bench.py` against each → recorded RPS/p50/p95/p99/status. No shared state between the two servers except Postgres. Cleanup trap removes containers/processes. Numbers are labeled as a local snapshot with caveats (macOS ephemeral limits, single run, trivial read).

### 4. Plan alignment — pass (with one open item)

Implements Phase 12 tasks 1-3 and 5-7. Task 4 (tune pool/workers) is documented as knobs rather than applied to a production deployment — appropriate since there is no production target env yet. Acceptance criteria 1-2 (P95/throughput) require human target agreement, surfaced as the open checkpoint. Criteria 3-4 (Docker/k8s updated; release-candidate reports) are met via `docs/performance.md`, `docs/migration-guide.md`, and this review.

### 5. Clean code / security / performance — pass

- Non-root container, no secret defaults, JWT key via secret in k8s manifest, `PREST_DEBUG=false` in prod compose.
- `bench.py` is small, typed, lint-clean; handles errors without crashing; warmup avoids first-request skew.
- `run-baseline.sh` cleans up containers/processes/ports; waits for readiness before benchmarking.
- Tuning doc honestly lists known limits (statement_cache_size, orjson, `--workers` not exposed) rather than claiming parity.
- Baseline shows no catastrophic regression; Python competitive with Go on the measured workload.

## Findings fixed during review

None blocking. One process improvement applied during the work: first baseline run used the wrong Go invocation (`--host/--port` flags Go does not accept); fixed to `PREST_HTTP_HOST/PORT` env vars with a readiness wait, yielding clean 200 responses.

## Verification

```text
ruff check prest_py tests/python scripts/bench.py   passed
pytest tests/python -q                                302 passed
uv lock --check                                       passed
uv build                                              passed
docker compose -f docker-compose-prod-python.yml config -q   passed
k8s deployment-python.yaml (yaml.safe_load)          passed
docker build Dockerfile.python                        passed
docker smoke (non-root uid 1001 + /_health 503)       passed
make test-contract-python CONTRACT_ARGS=-q            62 passed, 15 skipped
```

## Open checkpoints (human)

1. Accept/adjust proposed performance targets (P95 ≤ 1.5×Go, RPS ≥ 0.8×Go, no contract regressions).
2. Decide whether write/batch/scripts/auth paths must be benchmarked before Phase 12 sign-off, or defer to a Phase 12.1 and ship read parity + harness now.

## Residual risks

- Baseline is local/macOS/single-run; production Linux numbers will differ. Re-run `scripts/run-baseline.sh` on the target environment before declaring parity.
- `uvicorn --workers` not exposed via `prestd` CLI; multi-process deployments must use `uvicorn prest_py.app:create_app --factory --workers N` directly (documented in `docs/tuning.md`).
- JWKS/OpenID, orjson responses, and `statement_cache_size` are documented gaps, not Phase 12 blockers.