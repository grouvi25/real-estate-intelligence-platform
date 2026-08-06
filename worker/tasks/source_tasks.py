"""Source discovery Celery tasks. TZ section 15.3."""
from __future__ import annotations

import structlog
from celery import shared_task

from worker.async_runner import run_async

logger = structlog.get_logger()


async def _discover_for_geo(session, geo) -> int:
    """Find and evaluate sources for one geo. Returns how many were saved."""
    from app.discovery.source_finder import (
        evaluate_and_save_sources,
        search_telegram_sources,
        search_vk_sources,
    )

    # Both channels, scored by the same prompt: VK groups are where a regional
    # audience sits, and Telegram search over a small city returns mostly flea
    # markets.
    candidates = await search_telegram_sources(geo.keywords or {})
    candidates += await search_vk_sources(geo.keywords or {})
    if not candidates:
        return 0
    return await evaluate_and_save_sources(
        session, candidates, geo.id,
        {"agency_id": geo.agency_id, "city_name": geo.city_name},
    )


async def _geo_discovery_cron() -> int:
    """Weekly auto-discovery across all active geos with discovery enabled."""
    from sqlalchemy import select

    from app.database import async_session
    from app.models.geo_location import GeoLocation

    total = 0
    async with async_session() as session:
        stmt = select(GeoLocation).where(
            GeoLocation.is_active.is_(True),
            GeoLocation.auto_discovery_enabled.is_(True),
        )
        geos = (await session.execute(stmt)).scalars().all()
        for geo in geos:
            total += await _discover_for_geo(session, geo)
    logger.info("Geo discovery cron finished", geos=len(geos), sources_saved=total)
    return total


@shared_task(name="worker.tasks.source_tasks.geo_discovery_cron")
def geo_discovery_cron() -> int:
    return run_async(_geo_discovery_cron())


async def _discover_sources_for_geo(geo_id: str) -> int:
    """Discovery for a city that was just added.

    POST /api/geo answers "discovery_started", and until this existed that was
    not true: adding a city only queued keyword generation, and the city then sat
    without a single source until the weekly cron came round on Monday. Nothing
    reported it -- the screen simply stayed empty for up to a week.
    """
    from app.database import async_session
    from app.models.geo_location import GeoLocation

    async with async_session() as session:
        geo = await session.get(GeoLocation, geo_id)
        if geo is None:
            logger.warning("Geo not found for discovery", geo_id=geo_id)
            return 0
        if not (geo.keywords or {}):
            # Search queries come from the keywords; without them discovery would
            # look through an empty vocabulary and quietly find nothing.
            logger.warning("Geo has no keywords yet; discovery skipped", geo_id=geo_id)
            return 0
        saved = await _discover_for_geo(session, geo)

    logger.info("Geo discovery finished", geo_id=geo_id, sources_saved=saved)
    return saved


@shared_task(name="worker.tasks.source_tasks.discover_sources_for_geo")
def discover_sources_for_geo(geo_id: str) -> int:
    return run_async(_discover_sources_for_geo(geo_id))
