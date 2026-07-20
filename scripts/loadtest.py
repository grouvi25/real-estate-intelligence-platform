"""Standalone load test for REIP. TZ section 35 (50 RPS target).

Fires a steady request rate at lightweight, un-rate-limited endpoints and reports
latency percentiles and error rate. Deliberately NOT wired into the app or CI.
Point it at a dedicated/staging instance or the public TLS URL.

Usage:
    python scripts/loadtest.py --url https://reip.grouvi.online --rps 50 --seconds 30

Requires httpx (already a project dependency).
"""
from __future__ import annotations

import argparse
import asyncio
import time

import httpx

# Lightweight, un-rate-limited endpoints (health/liveness). Rotating between the
# root liveness probe and the versioned API health keeps both paths warm.
ENDPOINTS = ["/health", "/api/health"]


async def _one(client: httpx.AsyncClient, base: str, i: int, results: list) -> None:
    start = time.perf_counter()
    ok = False
    try:
        r = await client.get(f"{base}{ENDPOINTS[i % len(ENDPOINTS)]}", timeout=10)
        ok = r.status_code < 400
    except Exception:  # noqa: BLE001
        ok = False
    results.append((time.perf_counter() - start, ok))


async def run(base: str, rps: int, seconds: int) -> None:
    results: list[tuple[float, bool]] = []
    interval = 1.0 / rps
    async with httpx.AsyncClient() as client:
        tasks: list[asyncio.Task] = []
        deadline = time.perf_counter() + seconds
        n = 0
        while time.perf_counter() < deadline:
            tasks.append(asyncio.create_task(_one(client, base, n, results)))
            n += 1
            await asyncio.sleep(interval)
        await asyncio.gather(*tasks)

    latencies = sorted(r[0] for r in results)
    errors = sum(1 for r in results if not r[1])
    total = len(results) or 1

    def pct(p: float) -> float:
        idx = min(len(latencies) - 1, int(len(latencies) * p))
        return latencies[idx] * 1000 if latencies else 0.0

    print(f"requests:   {total}")
    print(f"target rps: {rps} (~{total / seconds:.1f} actual)")
    print(f"errors:     {errors} ({errors / total * 100:.1f}%)")
    print(f"p50:        {pct(0.50):.0f} ms")
    print(f"p95:        {pct(0.95):.0f} ms")
    print(f"p99:        {pct(0.99):.0f} ms")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--rps", type=int, default=50)
    ap.add_argument("--seconds", type=int, default=30)
    args = ap.parse_args()
    print(f"Load test: {args.url} @ {args.rps} RPS for {args.seconds}s")
    asyncio.run(run(args.url.rstrip("/"), args.rps, args.seconds))


if __name__ == "__main__":
    main()
