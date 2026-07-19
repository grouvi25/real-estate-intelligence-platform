"""Maintenance Celery tasks. TZ section 27.0 (reset_daily_ai_cost).

The logic is split into a plain async function (``_reset_daily_ai_cost``) for
testability and a thin @shared_task wrapper that runs it via asyncio.run().
"""
from __future__ import annotations

import asyncio

import structlog
from celery import shared_task

from app.config import config

logger = structlog.get_logger()


async def _reset_daily_ai_cost() -> int:
    """Reset the daily AI-cost counters (global + per agency). Returns agency count."""
    from sqlalchemy import select

    from app.database import async_session
    from app.models.agency import Agency
    from app.services.ai_cost_tracker import RedisCostTracker

    tracker = RedisCostTracker(config.redis_url)
    count = 0
    try:
        async with async_session() as session:
            agencies = (await session.execute(select(Agency))).scalars().all()
            for agency in agencies:
                await tracker.reset_daily_cost(str(agency.id))
                count += 1
        await tracker.reset_daily_cost("global")
    finally:
        await tracker.redis.aclose()
    logger.info("Daily AI cost reset", agencies=count)
    return count


@shared_task(name="worker.tasks.maintenance_tasks.reset_daily_ai_cost")
def reset_daily_ai_cost() -> int:
    return asyncio.run(_reset_daily_ai_cost())
