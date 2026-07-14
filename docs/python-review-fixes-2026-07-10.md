# pREST Python Review Repair Summary

**Date:** 2026-07-10  
**Source review:** `docs/python-review-phases-0-9-2026-07-10.md`

## Outcome

All six critical review blockers were addressed. Python default, multi-cluster, and auth services now run the frozen non-destructive contract suite in Docker.

## Critical fixes

1. **Pool creation:** replaced unsupported asyncpg option; added single-flight pool creation, supported pool-limit/connect-timeout mapping, encoded credentials, and certificate SSL contexts.
2. **Cache authorization bypass:** global policy executes before cache; authenticated CRUD is excluded from URL-keyed caching; health/readiness are never cached; cache size is bounded with expiry sweeping.
3. **User-specific fields:** select flow now passes authenticated username into field permission resolution, with cross-user regression coverage.
4. **Security config:** implemented global `jwt.default`, listing exposure policy, and HTTP Basic login. Unsupported JWKS/discovery settings fail during app creation rather than silently running unprotected.
5. **Auth SQL:** fixed empty database qualification in auth query. Review claim that legacy three-part references were invalid was disproven against PostgreSQL: current-database `database.schema.table` qualification works when the legacy pool connects to that same database.
6. **Batch boundary:** validates/quotes columns, requires homogeneous object records, rejects malformed bodies with 400, and keeps raw column names separately for asyncpg COPY.

## Important fixes

- Python list values now reach asyncpg array codecs directly; array insert was verified against PostgreSQL.
- Script headers resolve case-insensitively; `isSet`/`split` match Go output; script paths use resolved component containment and regular-file checks.
- Added XML response renderer matching frozen `<objects><object>…` contract.
- Catalog returns safe PostgreSQL undefined-column contract text while retaining generic responses for other DB failures.
- Count-first JSON uses compact Go-compatible encoding.
- Normalized group aggregate expressions are accepted through select field validation.
- Empty auth request body maps to Go-compatible 401; malformed non-empty JSON remains 400.
- Config loader isolates explicit empty env, tolerates malformed TOML, restores invalid values to defaults, and skips invalid registry URLs/profiles.
- Docker installs runtime dependencies from frozen `uv.lock` using pinned uv.
- Added Python unit/lint CI and Python contract CI.
- Repository Python Ruff gate now covers source and tests and passes.

## Verification topology

`docker-compose-test.yml` now provides:

- `prestd-python`
- `prestd-python-multicluster`
- `prestd-python-auth`
- `contract-tests-python`

Command:

```sh
make test-contract-python CONTRACT_ARGS="-q"
```

Latest repair-run results:

```text
Non-destructive: 62 passed, 15 skipped
Destructive:     77 passed
```

Destructive cases remain opt-in for routine CI.

## Explicitly deferred, not claimed complete

- Full DDD application-port extraction: owner accepted incremental extraction alongside Phase 10 instead of a risky repair-batch rewrite.
- Full Go `text/template` control structures: current documented subset covers existing repository examples.
- JWKS and `.well-known` resolution: configured use fails closed until implemented.
- CORS/context-prefix parity and static typecheck: tracked for later compatibility/architecture work; not part of frozen Phase 0 HTTP cases.

## Post-fix five-facet review

**Verdict: approve Phase 10 — no remaining blocking finding.**

1. **DDD boundaries:** no new inversion from repairs. Security/cache/rendering remain transport-owned; parameter coercion remains infrastructure-owned; config leniency remains settings-owned. Existing fat routes/private CRUD-helper imports remain accepted incremental architecture debt.
2. **Module architecture:** middleware order is XML renderer → global JWT/exposure → cache → route dependencies. Pool creation is single-flight and startup verifies DB connectivity. Explicit prepare/coercion is centralized in executor.
3. **Data flow:** Python passes all 77 frozen contract cases, including destructive CRUD/scripts/XML, default legacy routing, registry multi-cluster routing, auth server, catalog, and health/readiness.
4. **Planning:** plan and contract docs distinguish verified behavior from accepted deferrals. Plugin strategy is resolved; migration/performance decisions remain open in their intended phases.
5. **Clean code/security/performance:** Ruff passes; 271 Python tests pass; dependency audit reports no known vulnerabilities. SQL params/interpolated script data and malformed DSNs are not logged. Dead mutable pool state was removed.

Non-blocking follow-ups:

- Benchmark explicit prepare/type coercion during Phase 12 performance work.
- Resolve upstream FastAPI TestClient deprecation warning when the stack's `httpx2` migration path stabilizes.
- Run production container as non-root during Phase 12 deployment hardening.
