"""Tests for the Redis-backed rate limiter."""
import fakeredis.aioredis
import pytest

from app.services.rate_limit import RateLimiter


@pytest.fixture
def limiter():
    rl = RateLimiter.__new__(RateLimiter)
    rl.redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return rl


@pytest.mark.asyncio
async def test_allows_up_to_limit(limiter):
    for _ in range(5):
        assert await limiter.hit("ip1", limit=5, window=60) is True


@pytest.mark.asyncio
async def test_blocks_over_limit(limiter):
    for _ in range(5):
        await limiter.hit("ip1", limit=5, window=60)
    assert await limiter.hit("ip1", limit=5, window=60) is False


@pytest.mark.asyncio
async def test_separate_keys_independent(limiter):
    for _ in range(5):
        await limiter.hit("ip1", limit=5, window=60)
    # A different identifier has its own budget.
    assert await limiter.hit("ip2", limit=5, window=60) is True
