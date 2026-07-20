"""Standalone load test for REIP. TZ section 35 (50 RPS target).

Fires a steady request rate at public endpoints and reports latency percentiles
and error rate. Deliberately NOT wired into the app or CI, and NOT pointed at the
shared dev VPS by default — run it against a dedicated/staging instance.

Usage:
    python scripts/loadtest.py --url http://localhost:8000 --rps 50 --seconds 30

Requires httpx (already a project dependency).
"""
from __future__ import annotations

import argparse
import asyncio
import time

import httpx

# Public, cheap endpoints (no auth, no PII, no persistence).
MORTGAGE_BODY = {
    "property_price": 8_000_000, "down_payment": 2_000_000,
    "term_years": 20, "program": "family",
}


async def _one(client: httpx.AsyncClient, base: str, results: list) -> None:
    start = time.perf_counter()
    ok = False
    try:
        # Alternate between a trivial GET and a compute POST.
        if int(start * 1000) % 2 == 0:
            r = await client.get(f"{base}/health", timeout=10)
        else:
            r = await client.post(f"{base}/api/lm/lm2/calculate", json=MORTGAGE_BODY, timeout=10)
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
            tasks.append(asyncio.create_task(_one(client, base, results)))
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
