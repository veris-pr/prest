# pREST contract tests

Black-box tests for the Python rewrite contract freeze.

These tests run against deployed pREST servers by URL. Go is the oracle target until Python parity is complete.

Internal Docker service ports are OK. If exposing services to the host for manual runs, use only ports in `20000-29999` because other local projects already use PostgreSQL, Redis, and FastAPI ports.

## Run against Go oracle

Preferred command:

```sh
make test-contract-go
```

Pass extra pytest flags through `CONTRACT_ARGS`:

```sh
make test-contract-go CONTRACT_ARGS="-q --run-destructive-contract"
```

Manual run against already deployed Go servers:

```sh
python3 -m pip install -r tests/contract/requirements.txt
PREST_TEST_URL=http://prestd:3000 \
PREST_MULTICLUSTER_TEST_URL=http://prestd-multicluster:3001 \
PREST_AUTH_TEST_URL=http://prestd-auth:3002 \
python3 -m pytest tests/contract --target=go
```

## Run against Python target

```sh
PY_PREST_TEST_URL=http://localhost:3000 \
PY_PREST_MULTICLUSTER_TEST_URL=http://localhost:3001 \
PY_PREST_AUTH_TEST_URL=http://localhost:3002 \
python3 -m pytest tests/contract --target=python
```

## CI

`.github/workflows/test-contract.yml` runs the Go oracle contract suite with:

```sh
make test-contract-go CONTRACT_ARGS="-q"
```

It runs on `workflow_dispatch`, on `main`/tag pushes touching contract-related files, and on PRs touching contract-related files.

## Current Go oracle baseline

Non-destructive run:

```sh
make test-contract-go CONTRACT_ARGS="-q"
```

Current result: `62 passed, 15 skipped`.

## Destructive cases

Write/delete/update cases are skipped by default because they mutate seeded DB state. Enable them explicitly:

```sh
make test-contract-go CONTRACT_ARGS="--run-destructive-contract"
```

## Source of truth

Cases are derived from:

- `integration/controllers/catalog_test.go`
- `integration/controllers/crud_test.go`
- `integration/controllers/scripts_test.go`
- `integration/controllers/auth_test.go`
- `integration/controllers/health_test.go`
- `integration/controllers/ready_test.go`
- `integration/controllers/multicluster_test.go`

See `docs/python-contract-freeze.md` for route/status matrix and divergence rules.
