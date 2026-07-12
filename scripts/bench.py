#!/usr/bin/env python3
"""pREST load-test client.

Async HTTP load generator using httpx. No external benchmark binary needed.
Measures requests/sec and P50/P95/P99 latency for a single endpoint.

Usage:
    python scripts/bench.py --url http://127.0.0.1:23000/prest-test/public/test \
        --duration 20 --concurrency 50

Exit code 0 on success, non-zero on setup error.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time

import httpx


async def _worker(
    client: httpx.AsyncClient,
    url: str,
    deadline: float,
    latencies: list[float],
    status_counts: dict[int, int],
) -> None:
    while time.monotonic() < deadline:
        start = time.monotonic()
        try:
            response = await client.get(url, timeout=10.0)
            status_counts[response.status_code] = (
                status_counts.get(response.status_code, 0) + 1
            )
        except Exception:
            status_counts[0] = status_counts.get(0, 0) + 1
        latencies.append((time.monotonic() - start) * 1000.0)


async def run(url: str, duration: int, concurrency: int) -> int:
    latencies: list[float] = []
    status_counts: dict[int, int] = {}
    deadline = time.monotonic() + duration
    async with httpx.AsyncClient() as client:
        # Warmup one request so first-request cost does not skew percentiles.
        try:
            await client.get(url, timeout=10.0)
        except Exception:  # noqa: S110  warmup best-effort
            pass
        workers = [
            asyncio.create_task(_worker(client, url, deadline, latencies, status_counts))
            for _ in range(concurrency)
        ]
        await asyncio.gather(*workers)

    if not latencies:
        print("no completed requests", file=sys.stderr)
        return 1

    latencies.sort()
    total = len(latencies)
    elapsed = duration
    rps = total / elapsed

    def pct(p: float) -> float:
        idx = max(0, min(total - 1, int(total * p) - 1))
        return latencies[idx]

    print(f"url={url} concurrency={concurrency} duration={duration}s")
    print(f"requests={total} rps={rps:.1f}")
    print(f"latency_ms p50={pct(0.50):.2f} p95={pct(0.95):.2f} p99={pct(0.99):.2f} "
          f"max={latencies[-1]:.2f}")
    print(f"status_counts={dict(sorted(status_counts.items()))}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="pREST async load-test client")
    parser.add_argument("--url", required=True, help="Target URL to GET")
    parser.add_argument("--duration", type=int, default=15, help="Test duration seconds")
    parser.add_argument("--concurrency", type=int, default=50, help="Concurrent workers")
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args.url, args.duration, args.concurrency)))


if __name__ == "__main__":
    main()