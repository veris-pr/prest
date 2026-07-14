# Tutorial 2 — Require a login

In this tutorial we will gate the `tasks` table behind a JWT, watch a request
without a token get rejected, then mint a token and get back in. When you
finish, you will understand how pREST protects endpoints.

Builds on [Tutorial 1](getting-started.md). You need Docker and the tutorial
stack running.

## 1. Start with auth on

We will layer an auth override on top of the tutorial compose. The override
turns on `jwt.default` and sets the HMAC signing key.

```sh
docker compose -f docker-compose-tutorial.yml \
  -f docker-compose-tutorial-auth.yml up -d --build
```

Give it a few seconds, then check it answered:

```sh
curl -i http://127.0.0.1:23000/_health
```

You will get HTTP `401` with `{"error":"authorization token is empty"}`.

That `401` is the point: with `jwt.default` on, JWT validation runs on **every**
path except the whitelist. Even `/_health` is gated. A `401` here proves the
server is up and the gate is active.

> In production you whitelist the probe paths so Kubernetes liveness/readiness
> can reach them without a token, e.g. `jwt.whitelist = ["^/_health$", "^/_ready$"]`
> in your `prest.toml`. We skip that here so you can see the raw behavior.

## 2. Seed the table

```sh
docker compose -f docker-compose-tutorial.yml exec -T postgres \
  psql -U prest -d prest -c "
    CREATE TABLE tasks (id serial PRIMARY KEY, title text NOT NULL, done boolean DEFAULT false);
    INSERT INTO tasks (title, done) VALUES ('write tutorial', false);
  "
```

## 3. Try to read without a token

```sh
curl -i http://127.0.0.1:23000/prest/public/tasks
```

`401`, `{"detail":"authorization token is empty"}`. The table is behind a login.

## 4. Mint a token

pREST validates HS256 JWTs signed with the key we set. We will mint one inside
the running server container, which already has PyJWT:

```sh
TOKEN=$(docker compose -f docker-compose-tutorial.yml exec -T prest-python \
  python -c "import jwt,time; print(jwt.encode({'UserInfo':{'username':'alice'},'nbf':int(time.time()),'exp':int(time.time())+3600}, 'tutorial-secret-key-at-least-32-bytes-long', algorithm='HS256'))")
echo $TOKEN
```

You will see a long `eyJ...` JWT string. (In production you issue tokens via
`POST /auth` after checking credentials — see `docs/reference.md`. Here we mint
one directly so we can focus on the gate.)

## 5. Read with the token

```sh
curl http://127.0.0.1:23000/prest/public/tasks \
  -H "Authorization: Bearer $TOKEN"
```

```json
[{"id":1,"title":"write tutorial","done":false}]
```

`200` — you are in.

## 6. Watch a bad token fail

```sh
curl -i http://127.0.0.1:23000/prest/public/tasks \
  -H "Authorization: Bearer not.a.real.token"
```

`401`, `{"detail":"failed JWT token parser"}`. The gate rejects anything that
does not verify against the configured key.

## 7. Clean up

```sh
docker compose -f docker-compose-tutorial.yml -f docker-compose-tutorial-auth.yml \
  down -v --remove-orphans
```

## What you did

You turned `jwt.default` on, saw requests without a valid token rejected (even
on `/_health`), and minted a token to get through. JWT validation is a **global**
policy; table-level permissions (`access.tables`) are a separate, finer control
— see `docs/reference.md` and `docs/architecture.md` "Auth & access control".

## Next

- [Tutorial 3 — Save and run a SQL script](save-a-query.md): author a `.sql`
  file and expose it as an endpoint.
- `docs/reference.md`: JWT config keys and the `/auth` endpoint.