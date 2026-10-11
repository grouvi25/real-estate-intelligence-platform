"""Source discovery Celery tasks. TZ section 15.3."""
from __future__ import annotations

import structlog
from celery import shared_task

from worker.async_runner import run_async

logger = structlog.get_logger()


async def _geo_discovery_cron() -> int:
    """Old weekly entry point, kept so a beat schedule saved before the upgrade
    does not hit an unregistered task. It hands every due city to the hourly
    discovery pipeline (worker/tasks/discovery.py) and returns how many."""
    from datetime import datetime, timezone

    from worker.tasks.discovery import QUEUE, _due_geo_ids, run_discovery_for_geo

    geo_ids = await _due_geo_ids(datetime.now(timezone.utc))
    for geo_id in geo_ids:
        run_discovery_for_geo.apply_async(args=[geo_id], queue=QUEUE)
    return len(geo_ids)


@shared_task(name="worker.tasks.source_tasks.geo_discovery_cron")
def geo_discovery_cron() -> int:
    return run_async(_geo_discovery_cron())


async def _discover_sources_for_geo(geo_id: str) -> int:
    """Discovery for a city that was just added.

    POST /api/geo answers "discovery_started", and until this existed that was
    not true: adding a city only queued keyword generation, and the city then sat
    without a single source until the next scheduled run. Now it is the same
    hourly pipeline (app/services/discovery), started right away.
    """
    from app.database import async_session
    from app.models.geo_location import GeoLocation
    from app.services.discovery.scheduler import run_for_geo

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

    report = await run_for_geo(geo_id)
    saved = (report.activated + report.sandboxed) if report else 0
    logger.info("Geo discovery finished", geo_id=geo_id, sources_saved=saved)
    return saved


@shared_task(name="worker.tasks.source_tasks.discover_sources_for_geo")
def discover_sources_for_geo(geo_id: str) -> int:
    return run_async(_discover_sources_for_geo(geo_id), timeout=540)
