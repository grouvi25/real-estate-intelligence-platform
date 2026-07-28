"""Source discovery Celery tasks. TZ section 15.3."""
from __future__ import annotations

import structlog
from celery import shared_task

from worker.async_runner import run_async

logger = structlog.get_logger()


async def _geo_discovery_cron() -> int:
    """Weekly auto-discovery across all active geos with discovery enabled."""
    from sqlalchemy import select

    from app.database import async_session
    from app.discovery.source_finder import evaluate_and_save_sources, search_telegram_sources
    from app.models.geo_location import GeoLocation

    total = 0
    async with async_session() as session:
        stmt = select(GeoLocation).where(
            GeoLocation.is_active.is_(True),
            GeoLocation.auto_discovery_enabled.is_(True),
        )
        geos = (await session.execute(stmt)).scalars().all()
        for geo in geos:
            candidates = await search_telegram_sources(geo.keywords or {})
            if candidates:
                total += await evaluate_and_save_sources(
                    session,
                    candidates,
                    geo.id,
                    {"agency_id": geo.agency_id, "city_name": geo.city_name},
                )
    logger.info("Geo discovery cron finished", geos=len(geos), sources_saved=total)
    return total


@shared_task(name="worker.tasks.source_tasks.geo_discovery_cron")
def geo_discovery_cron() -> int:
    return run_async(_geo_discovery_cron())
