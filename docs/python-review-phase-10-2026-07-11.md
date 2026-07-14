# Python rewrite Phase 10 review — 2026-07-11

## Scope

Reviewed Python-native plugin implementation against the approved import-string plan and current Go plugin behavior:

- `prest_py/plugins/`
- `prest_py/app.py`
- `prest_py/settings/`
- plugin/settings tests
- `docs/python-plugins.md`

## Verdict

Phase 10 is complete and ready to proceed. No blocking findings remain.

## Facet results

### 1. DDD boundaries — pass

Plugin contracts are transport extensions, dynamic import is isolated in the plugin loader, settings owns config, and `app.py` remains the composition root. No domain module depends on FastAPI/plugin infrastructure. Existing core route-orchestration debt is unchanged rather than expanded.

### 2. Architecture fit — pass after fix

- Plugins load once during app creation.
- Exact plugin routes precede broad dynamic catalog/CRUD routes, matching Go reachability.
- Built-in XML/global policy/cache boundaries remain outside plugin middleware.
- Plugin middleware follows config order.
- Invalid ASGI middleware now fails app creation instead of the first request.

### 3. Data flow — pass after fix

Flow is deterministic:

```text
TOML/env → PluginsSettings → import-string loader → registration validation
→ app composition → global policy/cache → plugin middleware → route
```

Malformed plugin TOML/env values now fail startup instead of being repaired to an empty list by general lenient config handling. Docs explicitly state that cache hits skip plugin middleware and `auth.enabled` does not automatically protect custom plugin routes.

### 4. Plan alignment — pass

Implemented approved Python import-string API for FastAPI routes and middleware. Go `.so` ABI and compatibility route remain intentionally removed. No hot reload, lifecycle hooks, constructor options, or dependency graph were added.

### 5. Clean code/security/performance — pass after fix

Loader and immutable registration contract are small and direct. Trusted-code boundary is documented. Duplicate entries, invalid registrations, middleware construction failures, and exact path+method conflicts fail startup. Plugin imports cost startup only; request overhead is limited to configured middleware.

## Findings fixed during review

1. **Important — lazy middleware failure:** class-typed non-ASGI middleware failed on first request. App now eagerly builds plugin middleware stack and raises `PluginLoadError` during creation.
2. **Important — silent plugin disable:** malformed plugin value types were reset by lenient settings repair. Plugin section/env parsing is now strict.
3. **Important — route override:** plugin-first ordering could silently replace exact built-in/plugin routes. Startup now rejects overlapping path+method pairs while preserving precedence over broad dynamic route templates.
4. **Documentation — policy semantics:** documented trusted-code boundary, cache-hit middleware behavior, custom-route auth responsibility, ordering, and unsupported features.

## Verification

```text
ruff check prest_py tests/python                    passed
pytest tests/python -q                              293 passed, 1 dependency deprecation warning
uv lock --check                                     passed
python -m compileall -q prest_py                     passed
uv build                                             passed
Dockerfile.python locked build/import smoke          passed
make test-contract-python CONTRACT_ARGS="-q"         62 passed, 15 skipped
docker compose -f docker-compose-test.yml config -q passed
git diff --check                                     passed
```

Warning is existing FastAPI `TestClient` / Starlette `httpx` deprecation, not introduced by Phase 10.

## Residual risks

- Plugins execute with full pREST process permissions; package review remains operational policy.
- Route conflict scanning accounts for FastAPI 0.139 nested router wrappers and has regression coverage; recheck on FastAPI upgrades.
- Plugin middleware runs inside cache and must not host must-run security/audit controls.
- External plugin packages require a custom image/environment that installs them alongside pREST.
