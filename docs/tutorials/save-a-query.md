# Tutorial 3 — Save and run a SQL script

In this tutorial we will write a SQL file, expose it as an endpoint, and call
it with a parameter. When you finish, you will know how to ship a reusable
query as a URL.

Builds on [Tutorial 1](getting-started.md). You need Docker.

## 1. Start with scripts enabled

We will layer a scripts override on the tutorial compose. It mounts a local
`./tutorial-queries` directory into the container and points pREST at it.

```sh
docker compose -f docker-compose-tutorial.yml \
  -f docker-compose-tutorial-scripts.yml up -d --build
```

Check it answered:

```sh
curl -i http://127.0.0.1:23000/_health
```

`200` (this stack has auth off, so the health route is open).

## 2. Seed the table

```sh
docker compose -f docker-compose-tutorial.yml exec -T postgres \
  psql -U prest -d prest -c "
    CREATE TABLE tasks (id serial PRIMARY KEY, title text NOT NULL, done boolean DEFAULT false);
    INSERT INTO tasks (title, done) VALUES ('write tutorial', false), ('ship it', false), ('review PR', true);
  "
```

## 3. Write the script file

Create the directory and the script. The file's **name** decides the URL; the
**suffix** decides the HTTP method.

```sh
mkdir -p tutorial-queries/myapp
cat > tutorial-queries/myapp/get_open_tasks.read.sql <<'SQL'
SELECT id, title FROM tasks WHERE done = {{sqlVal "done"}} ORDER BY id
SQL
```

Two rules:

- The file lives at `tutorial-queries/myapp/get_open_tasks.read.sql`. The
  `.read.sql` suffix means this script answers `GET`.
- `{{sqlVal "done"}}` reads the `done` query parameter and emits a
  **parameterized** `$1` placeholder — never string-concatenated. That is the
  safe way to pass user input into a script.

## 4. Call the script

```sh
curl 'http://127.0.0.1:23000/_QUERIES/myapp/get_open_tasks?done=false'
```

```json
[{"id":1,"title":"write tutorial"},{"id":2,"title":"ship it"}]
```

The URL shape is `/_QUERIES/{queriesLocation}/{script}` — here
`/_QUERIES/myapp/get_open_tasks`. The `done=false` became `WHERE done = $1`
with `false` bound safely.

> For a specific database, prefix it: `/_QUERIES/{database}/{queriesLocation}/{script}`.

## 5. Change the method, change the suffix

To make a write script, name the file `...write.sql` (POST), `...update.sql`
(PUT/PATCH), or `...delete.sql` (DELETE). A `GET` to a `.write.sql` file returns
"could not get script" — the suffix must match the method.

## 6. Clean up

```sh
docker compose -f docker-compose-tutorial.yml -f docker-compose-tutorial-scripts.yml \
  down -v --remove-orphans
rm -rf tutorial-queries
```

## What you did

You turned a SQL file into a URL: `tutorial-queries/myapp/get_open_tasks.read.sql`
→ `GET /_QUERIES/myapp/get_open_tasks`. You passed a parameter through the
template safely with `sqlVal` (parameterized, not concatenated).

## Next

- `docs/reference.md`: every template function (`sqlVal`, `sqlList`,
  `limitOffset`, `defaultOrValue`, `ident`, …) and the full method/suffix map.
- `docs/architecture.md`: where scripts sit in the request lifecycle.
- `CONTRIBUTING.md`: how to add tests for a new endpoint.