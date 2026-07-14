# Contributing

This guide covers the **Python rewrite** (`prest_py/`). For contributing to
the Go implementation, see the
[official pREST development guide](https://docs.prestd.com/get-prest/development-guide).

New here? Start with `docs/onboarding.md`, then `docs/architecture.md`.

## Setup

You need Docker (for contract tests) and `uv` (Python tooling).

```sh
uv sync --extra dev          # install runtime + dev deps into .venv
uv run prestd version        # smoke: should print the tagline + version
```

Node/Go are not required to contribute to `prest_py/`. Go is only needed if
you also work on the Go binary or run `scripts/run-parity.sh`.

## The gates

Run these before pushing. They are the same checks CI runs.

```sh
# Lint — must be clean
uv run ruff check prest_py tests/python

# Format check (apply fixes with: uv run ruff format <files>)
uv run ruff format --check prest_py tests/python

# Unit tests — pure-Python, no DB, fast
uv run pytest tests/python -q

# Contract tests — HTTP behavior frozen against the Go binary (needs Docker)
make test-contract-python
# include write/destructive cases:
make test-contract-python CONTRACT_ARGS="--run-destructive-contract -q"

# Live Go-vs-Python parity (needs Go + Docker) — proves same DB, same responses
bash scripts/run-parity.sh

# Build + lock
uv lock --check
uv build
```

Acceptance bar for a merge: ruff clean, unit tests green, contract tests green
(or an explicit, reviewed reason a contract changed), lock + build pass.

## Conventions

- **Dependency direction is inward only.** See `docs/architecture.md`. `domain`
  and `settings` import no infra. `postgres` imports `domain`/`settings`. `api`
  imports `postgres`. Routes never import `app` or `cli`.
- **No SQL string-concatenation of user input.** Validate identifiers with
  `prest_py.domain.identifiers`; pass values via the `Query` dataclass
  parameterized placeholders (`$1`, `$2`, ...).
- **Fail closed on security.** If a config combination cannot be safely
  enforced, raise during app creation — do not start in a degraded state.
- **Contract parity first.** The Go binary is the oracle. If you change HTTP
  behavior, update or add a contract test in `tests/contract/` and explain the
  delta in your PR.
- **Public config keys are stable.** Adding a key is fine; renaming or
  repurposing one is a breaking change — call it out in the PR and
  `docs/migration-guide.md`.
- **Type hints + docstrings** on public functions. Ruff enforces a lot; match
  the surrounding style.

## How to add a route

1. Pick the right file in `prest_py/api/routes/` (or add one).
2. Create an `APIRouter`, define the handler with typed path params and a
   Pydantic model for request bodies if needed.
3. Register it in `prest_py/api/routes/__init__.py` `build_api_router()`.
   **Order matters:** register specific paths before the broad
   `/{database}/{schema}/{table}` CRUD pattern, or CRUD will swallow them.
4. If the route needs auth + access control, add
   `dependencies=[Depends(crud_protection)]` (see how `crud_router` is wired).
5. Add a unit test in `tests/python/` for the handler logic.
6. If the route must match Go behavior, add a contract test in
   `tests/contract/` and run `make test-contract-python`.

## How to add a config key

1. Add the field to the right model in `prest_py/settings/models.py` with a
   default and a docstring.
2. Add the env mapping in `prest_py/settings/loader.py` `_ENV_MAP` (or the
   registry section if it is a `[[databases]]` field).
3. Add a test in `tests/python/test_settings_loader.py`: TOML path + env
   override path.
4. If the key changes runtime behavior, note it in `docs/migration-guide.md`.

## How to change SQL generation

1. Edit `prest_py/postgres/query_builder.py`. Keep the `Query` dataclass
   (SQL fragment + ordered values). Never interpolate values.
2. Add/adjust a unit test in `tests/python/test_query_builder.py`.
3. If output JSON shape could change, run the contract suite —
   `make test-contract-python` — and add a contract case if needed.

## How to add a plugin extension point

1. Extend `prest_py/plugins/contracts.py` `PluginRegistration` (new field).
2. Validate it in `prest_py/plugins/loader.py` `_validate_registration`.
3. Wire it in `prest_py/app.py` (respect the middleware/route ordering rules in
   `docs/architecture.md`).
4. Add a fixture + test in `tests/python/test_plugins.py`.

## Testing checklist

- [ ] Unit test added/updated for pure logic (`tests/python/`).
- [ ] Contract test added/updated for HTTP behavior (`tests/contract/`).
- [ ] `uv run ruff check` clean.
- [ ] `uv run pytest tests/python -q` green.
- [ ] `make test-contract-python` green (or delta explained).
- [ ] No new dependency added without justification (keep the dep list small).

## PR description template

```markdown
## What
<one line>

## Why
<motivation; link issue if any>

## How
<key files + approach>

## Tests
- [ ] unit: <file>
- [ ] contract: <file or "n/a">
- [ ] gates: ruff / pytest / make test-contract-python

## Breaking changes
<config keys, env vars, endpoints, or "none">
```

## Repo layout (Python side)

```
prest_py/          Python rewrite source
  settings/        config models + loader
  domain/          pure rules (identifiers, permissions)
  postgres/        pool, query builder, executor, scripts
  api/             routes, deps, middleware
  cache/           in-memory response cache
  plugins/         import-string plugin contract + loader
  app.py           composition root
  cli.py           Typer CLI
  main.py          uvicorn import target
tests/python/      unit tests
tests/contract/    HTTP contract tests (Go oracle)
scripts/           bench, parity, baseline helpers
docs/              onboarding, architecture, migration, tuning, plugins
Dockerfile.python  production image (non-root)
docker-compose-prod-python.yml
```

## Need help

- Architecture: `docs/architecture.md`
- Onboarding/learning path: `docs/onboarding.md`
- Migrations (Go binary): `docs/python-migrations.md`
- Plugins: `docs/python-plugins.md`
- Cutover from Go: `docs/migration-guide.md`