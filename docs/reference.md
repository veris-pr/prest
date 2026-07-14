# Reference

Austere reference for the pREST Python server. State facts, no explanation.
For *why*, see `docs/architecture.md`. For *how to do X*, see `CONTRIBUTING.md`
and `docs/tutorials/`.

Source of truth: `prest_py/settings/models.py`, `prest_py/settings/loader.py`,
`prest_py/api/routes/`, `prest_py/cli.py`, `prest_py/postgres/query_builder.py`,
`prest_py/postgres/scripts.py`.

## CLI

```
prestd                      serve (default; uvicorn)
prestd serve-equivalent flags:
  --host STR                bind host            (default: settings.http.host)
  --port INT                bind port            (default: settings.http.port)
  --config STR              path to prest.toml   (default: ./prest.toml or PREST_CONF)
  --reload                  auto-reload (dev)
prestd version              print tagline + package version
prestd migrate <up|down|redo|reset|next|version>
                            STUB — exits 2, points to Go binary (migrations
                            stay on Go pREST; see docs/python-migrations.md)
```

Multi-worker serving is not exposed via `prestd`; use uvicorn directly:

```sh
uvicorn prest_py.app:create_app --factory --workers 4 --host 0.0.0.0 --port 3000
```

## Config keys

Priority: **defaults < TOML < env** (matches Go). Missing TOML is tolerated.
TOML-only keys (no env var): `auth.metadata`, `cache.endpoints[]`,
`access.tables[]`, `access.users[]`, `access.ignore_table[]`, `jwt.whitelist`,
`expose.*` has env, `databases[]` registry, `app_name`, `context`.

### top-level

| Key | Type | Default | Env |
|---|---|---|---|
| `app_name` | str | `pREST Python` | — |
| `config_path` | str | `./prest.toml` | `PREST_CONF` |
| `debug` | bool | `false` | `PREST_DEBUG` |
| `context` | str | `/` | `PREST_CONTEXT` |
| `json_agg_type` | str | `jsonb_agg` | `PREST_JSON_AGG_TYPE` |

`json_agg_type` ∈ {`jsonb_agg`, `json_agg`}.

### `[auth]`

| Key | Type | Default | Env |
|---|---|---|---|
| `enabled` | bool | `false` | `PREST_AUTH_ENABLED` |
| `username` | str | `username` | `PREST_AUTH_USERNAME` |
| `password` | str | `password` | `PREST_AUTH_PASSWORD` |
| `schema` | str | `public` | `PREST_AUTH_SCHEMA` |
| `table` | str | `prest_users` | `PREST_AUTH_TABLE` |
| `encrypt` | str | `bcrypt` | `PREST_AUTH_ENCRYPT` |
| `type` | str | `body` | `PREST_AUTH_TYPE` |
| `metadata` | list[str] | `[]` | — |

`encrypt` ∈ {`bcrypt`, `md5`, `sha1`}. `type` ∈ {`body`, `basic`}.

### `[http]`

| Key | Type | Default | Env |
|---|---|---|---|
| `host` | str | `0.0.0.0` | `PREST_HTTP_HOST` |
| `port` | int (1–65535) | `3000` | `PREST_HTTP_PORT` / `PORT` |
| `timeout` | int (≥0) | `60` | `PREST_HTTP_TIMEOUT` |

### `[pg]`

| Key | Type | Default | Env |
|---|---|---|---|
| `url` | str | `""` | `PREST_PG_URL` / `DATABASE_URL` |
| `host` | str | `127.0.0.1` | `PREST_PG_HOST` |
| `port` | int | `5432` | `PREST_PG_PORT` |
| `user` | str | `postgres` | `PREST_PG_USER` |
| `pass` | str | `postgres` | `PREST_PG_PASS` |
| `database` | str | `prest` | `PREST_PG_DATABASE` |
| `ssl.mode` | str | `disable` | `PREST_PG_SSL_MODE` |
| `ssl.cert` | str | `""` | `PREST_PG_SSL_CERT` |
| `ssl.key` | str | `""` | `PREST_PG_SSL_KEY` |
| `ssl.rootcert` | str | `""` | `PREST_PG_SSL_ROOTCERT` |
| `maxidleconn` | int | `0` | `PREST_PG_MAXIDLECONN` |
| `maxopenconn` | int | `10` | `PREST_PG_MAXOPENCONN` |
| `conntimeout` | int | `10` | `PREST_PG_CONNTIMEOUT` |
| `single` | bool | `true` | `PREST_PG_SINGLE` |
| `cache` | bool | `true` | `PREST_PG_CACHE` |

`ssl.mode` ∈ {`disable`, `allow`, `prefer`, `require`, `verify-ca`, `verify-full`}.

### `[cache]`

| Key | Type | Default | Env |
|---|---|---|---|
| `enabled` | bool | `false` | `PREST_CACHE_ENABLED` |
| `time` | int (minutes) | `10` | `PREST_CACHE_TIME` |
| `storagepath` | str | `./` | `PREST_CACHE_STORAGEPATH` |
| `sufixfile` | str | `.cache.prestd.db` | `PREST_CACHE_SUFIXFILE` |
| `endpoints[]` | list | `[]` | — |

Each `[[cache.endpoints]]`: `endpoint` str, `enabled` bool, `time` int.

### `[access]`

| Key | Type | Default | Env |
|---|---|---|---|
| `restrict` | bool | `false` | `PREST_ACCESS_RESTRICT` |
| `ignore_table` | list[str] | `[]` | — |
| `tables[]` | list | `[]` | — |
| `users[]` | list | `[]` | — |

`[[access.tables]]`: `database` str, `schema` str, `name` str, `permissions` list[str] (`read`/`write`/`delete`), `fields` list[str].
`[[access.users]]`: `name` str, `tables[]` (same shape as `access.tables`).

### `[expose]`

| Key | Type | Default | Env |
|---|---|---|---|
| `enabled` | bool | `false` | `PREST_EXPOSE_ENABLED` |
| `tables` | bool | `true` | `PREST_EXPOSE_TABLES` |
| `schemas` | bool | `true` | `PREST_EXPOSE_SCHEMAS` |
| `databases` | bool | `true` | `PREST_EXPOSE_DATABASES` |

### `[jwt]`

| Key | Type | Default | Env |
|---|---|---|---|
| `default` | bool | `false` | `PREST_JWT_DEFAULT` |
| `key` | str | `""` | `PREST_JWT_KEY` |
| `algo` | str | `HS256` | `PREST_JWT_ALGO` |
| `wellknownurl` | str | `""` | `PREST_JWT_WELLKNOWNURL` |
| `jwks` | str | `""` | `PREST_JWT_JWKS` |
| `whitelist` | list[str] | `[r"^\/auth$"]` | — |

`wellknownurl` and `jwks` are **rejected** by the Python runtime (asymmetric
auth not implemented). Use HMAC (`key`) only.

### `[queries]` / `[plugins]`

| Key | Type | Default | Env |
|---|---|---|---|
| `queries.location` | str | `""` | `PREST_QUERIES_LOCATION` |
| `plugins.entries` | list[str] | `[]` | `PREST_PLUGIN_ENTRIES` |

`PREST_PLUGIN_ENTRIES` accepts a JSON string array or comma-separated list.

### `[[databases]]` (registry, TOML-only)

| Key | Type | Default |
|---|---|---|
| `alias` | str (req) | — |
| `url` | str | `""` |
| `host`/`port`/`user`/`pass`/`database` | str/int | `""`/`0` |
| `ssl.*` | see `[pg].ssl` | `disable` |
| `maxopenconn`/`maxidleconn` | int | `0`/`0` (0 = inherit) |

Env registry alternative: `PREST_DATABASE_ALIAS_N` + `PREST_DATABASE_URL_N`
(or `DATABASE_ALIAS_N` + `DATABASE_URL_N`), contiguous 1-based index pairs.

## Endpoints

### Health (never CRUD-protected; gated by `jwt.default` like all paths)

| Method | Path | Returns |
|---|---|---|
| GET | `/_health` | 200 empty (liveness: pings default DB) / 503 |
| GET | `/_ready` | 200 empty (readiness: pings default + all aliases) / 503 |

### Auth

| Method | Path | Returns |
|---|---|---|
| POST | `/auth` | 200 `{user_info, token}` / 401 / 404 (auth disabled) / 500 (no jwt key) |

Body (`type=body`): `{"username": str, "password": str}`. With `type=basic`:
HTTP Basic header. Token = HS256 JWT, 6h expiry.

### Catalog

| Method | Path | Returns |
|---|---|---|
| GET | `/databases` | JSON list |
| GET | `/schemas` | JSON list |
| GET | `/tables` | JSON list |
| GET | `/{database}/{schema}` | tables in db/schema |
| GET | `/show/{database}/{schema}/{table}` | column metadata |

### CRUD (`/{database}/{schema}/{table}` — protected by `auth.enabled` + access control)

| Method | Path | Returns |
|---|---|---|
| GET | `/{database}/{schema}/{table}` | rows (JSON) |
| POST | `/{database}/{schema}/{table}` | 201 inserted row |
| POST | `/batch/{database}/{schema}/{table}` | 201 (header `Prest-Batch-Method: copy` → COPY) |
| PUT/PATCH | `/{database}/{schema}/{table}` | updated rows |
| DELETE | `/{database}/{schema}/{table}` | deleted rows |

Common errors: 400 invalid identifier / bad query / parse, 401 auth, 404
relation missing, 503 no DB.

### Scripts

| Method | Path |
|---|---|
| GET/POST/PUT/PATCH/DELETE | `/_QUERIES/{queriesLocation}/{script}` (default DB) |
| GET/POST/PUT/PATCH/DELETE | `/_QUERIES/{database}/{queriesLocation}/{script}` (specific DB) |

GET → `read` (jsonb_agg rows); others → `write` (rows_affected). Requires
`queries.location` set.

## CRUD query parameters

Reserved (control the query shape):

| Param | Effect |
|---|---|
| `_select` | comma-separated columns to return |
| `_count` | count query (e.g. `?_count=*`); with `_count_first` returns `{count, rows}` |
| `_groupby` | GROUP BY columns (enables group-function `_select`) |
| `_order` | ORDER BY (prefix `-` for DESC; e.g. `?_order=-id,name`) |
| `_page` + `_page_size` | pagination (1-based page) |
| `_distinct` | SELECT DISTINCT |
| `_join` | JOIN clauses (format `type:table:left_field:operator:right_field`) |
| `_or` | OR-grouped filters (semicolon-separated `field=cond`) |
| `_returning` | RETURNING clause (DELETE/PUT/PATCH) |

Filters: any non-`_` param is a WHERE filter. Syntax `field=value` (default
`$eq`) or `field=$op.value`.

| Op | SQL | | Op | SQL |
|---|---|---|---|---|
| `$eq` | `=` | | `$null` | `IS NULL` |
| `$ne` | `!=` | | `$notnull` | `IS NOT NULL` |
| `$gt` | `>` | | `$true` | `IS TRUE` |
| `$gte` | `>=` | | `$nottrue` | `IS NOT TRUE` |
| `$lt` | `<` | | `$false` | `IS FALSE` |
| `$lte` | `<=` | | `$notfalse` | `IS NOT FALSE` |
| `$in` | `IN` | | `$like` | `LIKE` |
| `$nin` | `NOT IN` | | `$ilike` | `ILIKE` |
| `$any` | `ANY` | | `$nlike` | `NOT LIKE` |
| `$some` | `SOME` | | `$nilike` | `NOT ILIKE` |
| `$all` | `ALL` | | | |

ltree: `$ltreelanc` → `@>`, `$ltreerdesc` → `<@`, `$ltreematch` → `~`, `$ltreematchtxt` → `@`.

Type suffixes on filter field: `field:jsonb` (JSONB access), `field:tsquery`
(tsquery). Group-function `_select` form: `func:arg:alias` (e.g.
`SUM:amount:total`) when `_groupby` set.

## Script template syntax

Method → file suffix:

| Method | Suffix |
|---|---|
| GET | `.read.sql` |
| POST | `.write.sql` |
| PUT, PATCH | `.update.sql` |
| DELETE | `.delete.sql` |

URL `/_QUERIES/{queriesLocation}/{script}` → file
`{queries.location}/{queriesLocation}/{script}{suffix}`.

Template blocks (Go `text/template` subset):

| Syntax | Effect |
|---|---|
| `{{.key}}` | substitute query param `key` (string-concat; use for labels) |
| `{{index .header "Name"}}` | request header (case-insensitive) |
| `{{sqlVal "key"}}` | parameterized `$n` placeholder + bind `key` value |
| `{{sqlList "key"}}` | `($n, $n+1, …)` + bind list `key` values |
| `{{ident "key"}}` | validated+quoted identifier from `key` |
| `{{defaultOrValue "key" "def"}}` | `key` or `def` if unset |
| `{{inFormat "key"}}` | `('a', 'b')` for a list value |
| `{{limitOffset "page" "size"}}` | `LIMIT size OFFSET(page-1)*size` |
| `{{isSet "key"}}` | `true`/`false` |
| `{{unEscape "value"}}` | URL-decode |
| `{{split "a,b,c" ","}}` | `[a b c]` (operates on literal arg) |

`sqlVal`/`sqlList` are stateful — placeholder IDs increment across calls.

## Status codes (common)

| Code | Meaning |
|---|---|
| 200 | OK |
| 201 | Created (insert) |
| 400 | invalid identifier / query / body parse |
| 401 | auth required / failed / access denied |
| 404 | relation not found / auth disabled on `/auth` |
| 500 | server error (e.g. jwt key missing) |
| 503 | database not available |