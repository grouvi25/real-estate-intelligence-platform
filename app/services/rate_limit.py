"""Redis-backed fixed-window rate limiting. TZ section 31 (security & infra).

Used to protect public endpoints (e.g. lead magnets) from abuse. If the limiter
isn't initialized (no Redis), the dependency is a no-op (fail-open) so the API
keeps working in minimal setups.
"""
from __future__ import annotations

import time
from typing import Optional

import redis.asyncio as aioredis
import structlog
from fastapi import Request

from app.exceptions import AppException

logger = structlog.get_logger()


class RateLimiter:
    def __init__(self, redis_url: str):
        self.redis = aioredis.from_url(redis_url, encoding="utf-8", decode_responses=True)

    async def hit(self, key: str, limit: int, window: int) -> bool:
        """Register a hit; return True if still within the limit for this window."""
        bucket = f"rl:{key}:{int(time.time() // window)}"
        count = await self.redis.incr(bucket)
        if count == 1:
            await self.redis.expire(bucket, window)
        return count <= limit


rate_limiter: Optional[RateLimiter] = None


def init_rate_limiter(redis_url: str) -> RateLimiter:
    global rate_limiter
    rate_limiter = RateLimiter(redis_url)
    return rate_limiter


def rate_limit(scope: str, limit: int = 30, window: int = 60):
    """FastAPI dependency factory: limit `limit` requests per `window` sec per IP."""

    async def _dependency(request: Request) -> None:
        if rate_limiter is None:
            return  # fail-open when not configured
        ident = request.client.host if request.client else "unknown"
        allowed = await rate_limiter.hit(f"{scope}:{ident}", limit, window)
        if not allowed:
            raise AppException(
                status_code=429,
                detail="Слишком много запросов, попробуйте позже",
                code="RATE_LIMITED",
            )

    return _dependency
