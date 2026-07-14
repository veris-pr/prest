#!/usr/bin/env python3
"""Live request/response parity check: Go pREST vs Python pREST.

Both servers run against the SAME Postgres. This script hits identical
endpoints on each and compares status code + normalized JSON body.

Educational port — functional/contract parity, not performance.

Usage:
    python scripts/parity-check.py --go http://127.0.0.1:23011 \
        --py http://127.0.0.1:23010 --db prest-test
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

import httpx


def _norm(value: Any) -> Any:
    """Recursively normalize JSON for comparison: sort dict keys, drop
    volatile fields (auto-generated ids we don't control across servers)."""
    if isinstance(value, dict):
        return {k: _norm(v) for k, v in sorted(value.items()) if k not in {"id"}}
    if isinstance(value, list):
        return [_norm(item) for item in value]
    return value


async def _fetch(client: httpx.AsyncClient, base: str, method: str, path: str, json_body=None):
    url = f"{base}{path}"
    try:
        resp = await client.request(method, url, json=json_body, timeout=10.0)
    except Exception as exc:
        return None, f"request error: {exc}"
    try:
        body = resp.json()
    except Exception:
        body = resp.text
    return resp.status_code, body


async def run(go_base: str, py_base: str, db: str) -> int:
    reads: list[tuple[str, str, str]] = [
        ("health", "GET", "/_health"),
        ("ready", "GET", "/_ready"),
        ("catalog public", "GET", f"/{db}/public"),
        ("list limit3", "GET", f"/{db}/public/test?_limit=3"),
        ("select+filter", "GET", f"/{db}/public/test?_select=name&_limit=2"),
        ("count", "GET", f"/{db}/public/test?_count=*"),
        ("by id", "GET", f"/{db}/public/test?id=1&_select=name"),
    ]

    failures = 0
    async with httpx.AsyncClient() as client:
        print(f"{'check':<20} {'go':<8} {'py':<8} {'parity':<8} detail")
        print("-" * 80)
        for label, method, path in reads:
            go_status, go_body = await _fetch(client, go_base, method, path)
            py_status, py_body = await _fetch(client, py_base, method, path)
            same_status = go_status == py_status
            same_body = _norm(go_body) == _norm(py_body)
            ok = same_status and same_body
            failures += 0 if ok else 1
            flag = "OK" if ok else "FAIL"
            detail = "" if ok else f"status go={go_status} py={py_status}; body differs"
            print(f"{label:<20} {str(go_status):<8} {str(py_status):<8} {flag:<8} {detail}")

        # Cross write/read: Python writes a row, Go reads it back (shared-DB proof).
        print("-" * 80)
        print("cross write/read (shared-DB proof):")
        write_name = "parity_probe_row"
        py_w_status, py_w_body = await _fetch(
            client, py_base, "POST", f"/{db}/public/test", {"name": write_name}
        )
        print(f"  POST (py)            status={py_w_status}")
        new_id = None
        if isinstance(py_w_body, list) and py_w_body:
            new_id = py_w_body[0].get("id")
        elif isinstance(py_w_body, dict):
            new_id = py_w_body.get("id")
        if new_id is None:
            print("  FAIL: could not read inserted id from Python response")
            failures += 1
        else:
            go_r_status, go_r_body = await _fetch(
                client, go_base, "GET", f"/{db}/public/test?id={new_id}&_select=name"
            )
            go_name = None
            if isinstance(go_r_body, list) and go_r_body:
                go_name = go_r_body[0].get("name")
            ok = go_r_status == 200 and go_name == write_name
            failures += 0 if ok else 1
            print(
                f"  GET (go) id={new_id}   status={go_r_status} name={go_name!r}  "
                f"{'OK' if ok else 'FAIL'}"
            )
            await _fetch(client, py_base, "DELETE", f"/{db}/public/test?id={new_id}")

    print("-" * 80)
    print(f"result: {failures} failure(s)")
    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Go vs Python pREST parity check")
    parser.add_argument("--go", required=True, help="Go pREST base URL")
    parser.add_argument("--py", required=True, help="Python pREST base URL")
    parser.add_argument("--db", default="prest-test", help="Database name in URL path")
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args.go, args.py, args.db)))


if __name__ == "__main__":
    main()