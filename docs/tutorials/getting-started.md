# Tutorial 1 — Turn a table into a REST API

In this tutorial we will start pREST, create a table, and read and write it
over HTTP. When you finish, you will have a working REST API over your own
Postgres table.

You need Docker. No Postgres install, no Go, no Python setup required.

## 1. Start pREST

We will use the tutorial compose, which starts Postgres and the Python server
together with auth off, so we can focus on the table.

```sh
docker compose -f docker-compose-tutorial.yml up -d --build
```

Wait a few seconds, then check the server is alive:

```sh
curl http://127.0.0.1:23000/_health
```

The response is empty with HTTP `200` when the database is reachable. If you
get `503`, wait 10 seconds and try again — Postgres is still starting.

> The server listens on host port `23000` (container port `3000`). The
> database is `prest`, user `prest`, password `prest`. Auth is off for this
> tutorial; [Tutorial 2](secure-an-endpoint.md) turns it on.

## 2. Create a table and add a row

We will make a `tasks` table in the `public` schema and insert two rows. Run
this against the Postgres container:

```sh
docker compose -f docker-compose-tutorial.yml exec -T postgres \
  psql -U prest -d prest -c "
    CREATE TABLE tasks (id serial PRIMARY KEY, title text NOT NULL, done boolean DEFAULT false);
    INSERT INTO tasks (title, done) VALUES ('write tutorial', false), ('ship it', false);
  "
```

You should see `CREATE TABLE` then `INSERT 0 2`.

## 3. Read the table

Ask pREST for all rows:

```sh
curl http://127.0.0.1:23000/prest/public/tasks
```

You will get JSON like:

```json
[{"id":1,"title":"write tutorial","done":false},{"id":2,"title":"ship it","done":false}]
```

The URL shape is `/{database}/{schema}/{table}` — here `/prest/public/tasks`.

> You just turned a Postgres table into a REST endpoint with zero code. That
> is the whole idea of pREST. (Why there are no table models in code is
> explained in `docs/architecture.md`.)

## 4. Add a row over HTTP

Send a POST with a JSON body. pREST turns it into an `INSERT`:

```sh
curl -X POST http://127.0.0.1:23000/prest/public/tasks \
  -H 'Content-Type: application/json' \
  -d '{"title":"review PR","done":false}'
```

You will get a `201` with the inserted row:

```json
{"id":3,"title":"review PR","done":false}
```

Notice the `id` came back as `3` — pREST returns the inserted row.

## 5. Filter and select columns

Ask for just the `title` of unfinished tasks:

```sh
curl 'http://127.0.0.1:23000/prest/public/tasks?_select=title&done=false'
```

```json
[{"title":"write tutorial"},{"title":"ship it"},{"title":"review PR"}]
```

`_select=title` picks columns. `done=false` is a filter that becomes a
parameterized `WHERE`. (The full list of query params is in `docs/reference.md`.)

## 6. Update and delete

Mark the first task done:

```sh
curl -X PATCH 'http://127.0.0.1:23000/prest/public/tasks?id=1' \
  -H 'Content-Type: application/json' \
  -d '{"done":true}'
```

Delete the review-PR task:

```sh
curl -X DELETE 'http://127.0.0.1:23000/prest/public/tasks?id=3'
```

`?id=1` means `WHERE id = 1` (the default operator is `$eq`). For other
operators use the `$op.value` form, e.g. `?id=$ne.1` — see `docs/reference.md`.

## 7. Clean up

```sh
docker compose -f docker-compose-tutorial.yml down -v --remove-orphans
```

## What you did

You served a Postgres table as REST with no code: list, insert, filter,
update, delete. The URL pattern `/{database}/{schema}/{table}` is the core of
pREST.

## Next

- [Tutorial 2 — Require a login](secure-an-endpoint.md): gate `tasks` behind a
  JWT so only logged-in users can read it.
- `docs/reference.md`: every query param and config key.
- `docs/architecture.md`: how a request flows from HTTP to Postgres.