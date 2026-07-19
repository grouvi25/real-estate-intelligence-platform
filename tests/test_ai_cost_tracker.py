"""Tests for RedisCostTracker using an in-memory fake Redis."""
import fakeredis.aioredis
import pytest

from app.services.ai_cost_tracker import RedisCostTracker


@pytest.fixture
def tracker():
    t = RedisCostTracker.__new__(RedisCostTracker)  # bypass __init__ (no real connection)
    t.redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return t


@pytest.mark.asyncio
async def test_starts_at_zero(tracker):
    assert await tracker.get_daily_cost() == 0.0


@pytest.mark.asyncio
async def test_add_accumulates(tracker):
    assert round(await tracker.add_cost(1.5), 2) == 1.5
    await tracker.add_cost(2.5)
    assert round(await tracker.get_daily_cost(), 2) == 4.0


@pytest.mark.asyncio
async def test_reset(tracker):
    await tracker.add_cost(5.0)
    await tracker.reset_daily_cost()
    assert await tracker.get_daily_cost() == 0.0


@pytest.mark.asyncio
async def test_per_agency_isolation(tracker):
    await tracker.add_cost(3.0, "agency-a")
    await tracker.add_cost(7.0, "agency-b")
    assert round(await tracker.get_daily_cost("agency-a"), 2) == 3.0
    assert round(await tracker.get_daily_cost("agency-b"), 2) == 7.0
    assert await tracker.get_daily_cost() == 0.0  # global untouched
