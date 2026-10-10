"""RateLimitGuard: no platform is asked more than it allows. ТЗ «Сигналы» 2.6.

Counters live in Redis, one per platform and time window, so several workers
share one budget. A searcher calls ``spend()`` before every request; ``check()``
filters the candidates before the sandbox test, which reads each of them again.

At 80% of a window the guard goes economical (only candidates with rank_score
above 0.7 pass); at 100% the platform waits for the next window.

Keys are per platform, not per token: every agency uses the same service token
and the same Telethon account, so their budgets are one budget.
"""
from __future__ import annotations

import time
from typing import Iterable, Optional

import structlog

from app.services.discovery.types import (
    CLASSIFIEDS,
    FORUM,
    OTZOVIK,
    RSS,
    TELEGRAM,
    TG_CATALOG,
    VK,
    WORDSTAT,
    YANDEX_MAPS,
    YOUTUBE,
    SourceCandidate,
)

logger = structlog.get_logger()

HOUR, DAY = 3600, 86400

# platform -> [(limit, window_seconds)]
LIMITS: dict[str, list[tuple[int, int]]] = {
    TELEGRAM: [(30, 600), (200, DAY)],
    VK: [(1000, DAY)],
    YOUTUBE: [(5000, DAY)],          # units: search.list = 100, other calls = 1
    RSS: [(10, 60)],                 # Google News
    FORUM: [(20, HOUR)],
    TG_CATALOG: [(20, HOUR)],
    OTZOVIK: [(20, HOUR)],
    CLASSIFIEDS: [(20, HOUR)],
    YANDEX_MAPS: [(1000, DAY)],
    WORDSTAT: [(200, DAY)],
}
ECONOMY_SHARE = 0.8
ECONOMY_MIN_RANK = 0.7


def redis_client():
    import redis.asyncio as redis  # noqa: PLC0415

    from app.config import config  # noqa: PLC0415

    return redis.from_url(config.redis_url, socket_connect_timeout=2, socket_timeout=2,
                          decode_responses=True)


def _key(platform: str, window: int, now: float) -> str:
    return f"rlg:{platform}:{window}:{int(now // window)}"


class RateLimitGuard:
    def __init__(self, budgets: Optional[dict] = None, now=time.time):
        """``budgets`` — the agency's platform_budgets: a lower daily figure
        there tightens the daily window, never loosens it."""
        self._now = now
        self.limits = {p: list(w) for p, w in LIMITS.items()}
        for platform, conf in (budgets or {}).items():
            daily = (conf or {}).get("daily_requests", (conf or {}).get("daily_units"))
            if isinstance(daily, int) and platform in self.limits:
                self.limits[platform] = [
                    (min(limit, daily), window) if window == DAY else (limit, window)
                    for limit, window in self.limits[platform]
                ] + ([] if any(w == DAY for _, w in self.limits[platform]) else [(daily, DAY)])

    async def _counts(self, client, platform: str) -> list[tuple[int, int, int]]:
        now = self._now()
        out = []
        for limit, window in self.limits.get(platform, []):
            used = int(await client.get(_key(platform, window, now)) or 0)
            out.append((used, limit, window))
        return out

    async def usage(self, platform: str) -> float:
        """Share of the tightest window already spent, 0..1+."""
        client = redis_client()
        try:
            counts = await self._counts(client, platform)
        except Exception as e:  # noqa: BLE001
            logger.warning("Rate guard without Redis", platform=platform, error=str(e)[:120])
            return 0.0
        finally:
            await client.aclose()
        return max((used / limit if limit else 1.0) for used, limit, _ in counts) if counts else 0.0

    async def spend(self, platform: str, cost: int = 1) -> bool:
        """Reserve ``cost`` requests/units. False — the platform is out of budget
        for now and the request must not be made."""
        client = redis_client()
        try:
            counts = await self._counts(client, platform)
            if any(used + cost > limit for used, limit, _ in counts):
                return False
            now = self._now()
            for _, _, window in counts:
                key = _key(platform, window, now)
                await client.incrby(key, cost)
                await client.expire(key, window + 60)
            return True
        except Exception as e:  # noqa: BLE001 - без Redis не останавливаемся
            logger.warning("Rate guard without Redis", platform=platform, error=str(e)[:120])
            return True
        finally:
            await client.aclose()

    async def check(self, candidates: Iterable[SourceCandidate]) -> list[SourceCandidate]:
        """Candidates whose platform still has room for the sandbox test."""
        usage: dict[str, float] = {}
        allowed = []
        for cand in candidates:
            if cand.platform not in usage:
                usage[cand.platform] = await self.usage(cand.platform)
                if usage[cand.platform] >= 1:
                    logger.warning("Discovery platform out of budget", platform=cand.platform)
                elif usage[cand.platform] >= ECONOMY_SHARE:
                    logger.warning("Discovery platform in economy mode", platform=cand.platform,
                                   usage=round(usage[cand.platform], 2))
            share = usage[cand.platform]
            if share >= 1:
                continue
            if share >= ECONOMY_SHARE and cand.rank_score <= ECONOMY_MIN_RANK:
                continue
            allowed.append(cand)
        return allowed
