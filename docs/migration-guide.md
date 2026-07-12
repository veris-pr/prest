# Migration guide: Go pREST → Python pREST

How to move a deployment from the Go `prestd` binary to the Python rewrite. Both talk to the same Postgres, so you can run them side by side and cut over per route.

## 1. Compatibility

| Area | Go | Python | Compatible? |
|---|---|---|---|
| Postgres | 9.5+ | 9.5+ (asyncpg) | same DB |
| Config | `prest.toml` + `PREST_*` env | same keys, same loader priority | yes |
| Endpoints | `/{db}/{schema}/{table}`, `/auth`, `/catalog`, `/_QUERIES`, `/_health`, `/_ready` | same | yes (contract-frozen) |
| Auth | HMAC JWT + JWKS/OpenID | HMAC JWT only | **partial — JWKS/OpenID not implemented** |
| Access control | `access.tables` / `access.users` | same | yes |
| Cache | BuntDB-backed | in-memory TTL | **format differs; cache is not shared/portable** |
| Plugins | Go `.so` + `/_PLUGIN/{file}/{func}` | Python import-string | **not compatible** |
| Migrations | `prestd migrate ...` (gosidekick) | stub → Go binary | **use Go binary for migrations** |
| CLI | `prestd` (cobra) | `prestd` (Typer) | names match; `migrate` stubs |

## 2. Config parity

The Python loader reads the same TOML sections and `PREST_*` env vars with the same priority (defaults < TOML < env). Existing `prest.toml` files work unchanged **except**:

- Remove `jwt.jwks` / `jwt.wellknownurl` — the Python runtime rejects them (asymmetric-key resolution not implemented). Use HMAC (`jwt.key`) or keep auth on the Go binary until JWKS lands.
- Go `.so` plugin config (`plugins.*` for `.so` paths) is replaced by `plugins.entries` import strings (see `docs/python-plugins.md`).
- `cache.*` semantics match but storage is in-memory; a restart clears the cache. No BuntDB file is read or written.

Run the contract suite to confirm your config is accepted:

```sh
make test-contract-python
```

## 3. Migrations

The Python binary does **not** run migrations. Keep the Go `prestd` binary (or a Go image) as the migration step in your pipeline:

```sh
prestd migrate up --path ./migrations --url "postgres://user:pass@host:5432/db?sslmode=disable"
```

See `docs/python-migrations.md`. The `public.schema_migrations` table and `.up.sql`/`.down.sql` files are unchanged because the DB is shared.

## 4. Plugins

Go `.so` plugins do not load. Replace each with a Python package exposing a `register()` callable returning `PluginRegistration` (FastAPI routers + middleware). See `docs/python-plugins.md` for the contract and ordering guarantees.

If a `.so` plugin implements custom SQL routes, port the SQL to a FastAPI router that calls the same Postgres via the app pool, or move the logic into `_QUERIES` script files.

## 5. Deployment shape

| Concern | Recommendation |
|---|---|
| API server | Python image: `prest/prest-python:<tag>`, CMD `prestd --host 0.0.0.0 --port 3000` |
| Migrations | Separate Go `prestd` image/step, run before rolling the API forward |
| Probes | unchanged: `/_health` (liveness), `/_ready` (readiness) |
| Workers | multiple uvicorn workers behind a reverse proxy; see `docs/tuning.md` |
| Secrets | same `PREST_*` env / secrets; add `PREST_JWT_KEY` for HMAC |

Example manifests: `install-manifests/kubernetes/deployment-python.yaml`, `docker-compose-prod-python.yml`.

## 6. Cut-over procedure

1. Run the Python contract suite against your config: `make test-contract-python`.
2. Deploy the Python image alongside the Go image (e.g. a canary deployment on a different port).
3. Run `scripts/run-baseline.sh` (or your own load test) against both; compare RPS/p95 in `docs/performance.md`.
4. Shift a fraction of traffic to Python; watch `/_health`, `/_ready`, error rates, and p95.
5. Run migrations with the Go binary before each schema change.
6. Cut over when metrics are stable. Keep the Go binary available for migrations.

## 7. Known gaps to plan around

- **JWKS / OpenID discovery** not supported — use HMAC JWT or keep auth on Go.
- **Cache storage** is in-memory only — not shared across replicas; consider Redis later.
- **Plugin ABI** changed — `.so` plugins must be ported to Python import-string plugins.
- **Migration engine** not reimplemented — Go binary stays.
- **uvicorn `--workers`** not exposed via `prestd` CLI — use `uvicorn prest_py.app:create_app --factory --workers N` for multi-process.

## 8. Rollback

Both binaries read the same DB and config. Rolling back to the Go binary is reverting the image/route; no data migration is needed. The `schema_migrations` table is owned by the Go binary throughout.