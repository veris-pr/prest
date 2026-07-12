# pREST Installation Manifests

Various installation / deployment methods for pREST.

## Go implementation (default)

- `kubernetes/deployment.yaml` — Go `prest/prest:v1` image, `/_health` + `/_ready` probes.
- `kubernetes/svc.yaml` — ClusterIP service.
- `../docker-compose-prod.yml` — local production-style compose.

## Python implementation (rewrite)

- `kubernetes/deployment-python.yaml` — `prest/prest-python:v1` image, same probes, same env vars. Run migrations separately via the Go binary (see `../docs/python-migrations.md`).
- `../docker-compose-prod-python.yml` — local production-style compose for the Python image.
- `../Dockerfile.python` — non-root, multi-stage, `prestd` CLI entrypoint.

Both implementations read the same `PREST_*` env vars and `prest.toml`. See `../docs/migration-guide.md` to cut over.