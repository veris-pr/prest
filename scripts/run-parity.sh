#!/usr/bin/env bash
# Host Go + Python pREST on different ports against ONE Postgres, then run a
# live request/response parity check. Educational port — functional parity.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY_PORT=23010
GO_PORT=23011
PG_PORT=25433
PG=prest_parity
DB=prest-test
USER=prest
PASS=prest

cleanup() {
  docker rm -f "$PG" >/dev/null 2>&1 || true
  pkill -f prestd-go 2>/dev/null || true
  pkill -f "prestd --host" 2>/dev/null || true
  lsof -ti:"$PY_PORT","$GO_PORT" 2>/dev/null | xargs kill -9 2>/dev/null || true
}
trap cleanup EXIT
cleanup

echo "==> starting postgres"
docker run -d --name "$PG" -p "$PG_PORT:5432" \
  -e POSTGRES_USER="$USER" -e POSTGRES_PASSWORD="$PASS" -e POSTGRES_DB="$DB" \
  postgres:16 >/dev/null
sleep 4
docker run --rm --link "$PG:pg" postgres:16 \
  psql "postgres://$USER:$PASS@pg:5432/$DB" \
  -c "CREATE TABLE IF NOT EXISTS test (id serial PRIMARY KEY, name text);" \
  -c "INSERT INTO test (name) SELECT 'row'||g FROM generate_series(1,1000) g;" >/dev/null

echo "==> building go prestd"
( cd "$ROOT" && CGO_ENABLED=0 go build -o /tmp/prestd-go ./cmd/prestd ) || { echo "go build failed"; exit 1; }

wait_http() {
  local url="$1"
  for _ in $(seq 1 40); do
    if curl -sf -o /dev/null "$url"; then return 0; fi
    sleep 0.5
  done
  return 1
}

echo "==> starting go prestd on :$GO_PORT"
PREST_PG_HOST=127.0.0.1 PREST_PG_PORT="$PG_PORT" PREST_PG_USER="$USER" PREST_PG_PASS="$PASS" \
PREST_PG_DATABASE="$DB" PREST_SSL_MODE=disable PREST_AUTH_ENABLED=false PREST_DEBUG=false \
PREST_HTTP_HOST=0.0.0.0 PREST_HTTP_PORT="$GO_PORT" \
/tmp/prestd-go >/tmp/prestd-go.log 2>&1 &
GO_PID=$!

echo "==> starting python prestd on :$PY_PORT"
PREST_PG_HOST=127.0.0.1 PREST_PG_PORT="$PG_PORT" PREST_PG_USER="$USER" PREST_PG_PASS="$PASS" \
PREST_PG_DATABASE="$DB" PREST_SSL_MODE=disable PREST_AUTH_ENABLED=false PREST_DEBUG=false \
uv run prestd --host 0.0.0.0 --port "$PY_PORT" >/tmp/prestd-py.log 2>&1 &
PY_PID=$!

wait_http "http://127.0.0.1:$GO_PORT/_health" || { echo "go not ready"; cat /tmp/prestd-go.log; exit 1; }
wait_http "http://127.0.0.1:$PY_PORT/_health" || { echo "py not ready"; cat /tmp/prestd-py.log; exit 1; }

echo "==> running parity check"
uv run python scripts/parity-check.py \
  --go "http://127.0.0.1:$GO_PORT" \
  --py "http://127.0.0.1:$PY_PORT" \
  --db "$DB"
RC=$?

kill "$GO_PID" "$PY_PID" 2>/dev/null || true
wait "$GO_PID" "$PY_PID" 2>/dev/null || true
echo "==> parity exit=$RC"
exit $RC