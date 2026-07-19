"""Thread-safe daily AI cost tracker backed by Redis. TZ section 27.0.

``INCRBYFLOAT`` is atomic, so the counter stays correct across N Celery workers
and API processes (the original ``self.daily_cost_rub`` gave each worker its own
independent counter).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis


class RedisCostTracker:
    """Per-agency (and global) daily AI spend counter."""

    def __init__(self, redis_url: str):
        self.redis = aioredis.from_url(redis_url, encoding="utf-8", decode_responses=True)

    def _key(self, agency_id: str = "global") -> str:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return f"ai:cost:{agency_id}:{today}"

    async def add_cost(self, cost_rub: float, agency_id: str = "global") -> float:
        key = self._key(agency_id)
        total = await self.redis.incrbyfloat(key, cost_rub)
        await self.redis.expire(key, 48 * 3600)
        return float(total)

    async def get_daily_cost(self, agency_id: str = "global") -> float:
        val = await self.redis.get(self._key(agency_id))
        return float(val) if val else 0.0

    async def reset_daily_cost(self, agency_id: str = "global") -> None:
        await self.redis.delete(self._key(agency_id))


# Singleton - initialized in app/main.py lifespan via init_cost_tracker().
cost_tracker: Optional[RedisCostTracker] = None


def init_cost_tracker(redis_url: str) -> RedisCostTracker:
    global cost_tracker
    cost_tracker = RedisCostTracker(redis_url)
    return cost_tracker
