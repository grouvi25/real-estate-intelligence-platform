"""Source discovery and source health. ТЗ «Сигналы» v1.0, раздел 5.

    run_discovery_for_all_agencies   hourly at :15 -- hands each due city to
                                     run_discovery_for_geo (one task per city:
                                     a city takes 1-3 minutes, and the worker's
                                     ceiling is per task)
    check_source_health              hourly at :45
    retry_sandbox_candidates         daily

All of them go to the "discovery" queue, so discovery never queues ahead of
collection and signal scoring.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from celery import shared_task

from worker.async_runner import run_async

logger = structlog.get_logger()

QUEUE = "discovery"
GEO_TIMEOUT = 540


async def _due_geo_ids(now: datetime) -> list[str]:
    from sqlalchemy import func, select  # noqa: PLC0415

    from app.database import async_session  # noqa: PLC0415
    from app.models.agency import Agency  # noqa: PLC0415
    from app.models.discovery import DiscoveryLog  # noqa: PLC0415
    from app.models.geo_location import GeoLocation  # noqa: PLC0415
    from app.services.billing import collectable_agencies_clause  # noqa: PLC0415
    from app.services.discovery.settings import discovery_settings  # noqa: PLC0415

    due = []
    async with async_session() as session:
        agencies = (await session.execute(select(Agency).where(
            collectable_agencies_clause()))).scalars().all()
        last_runs = dict((await session.execute(
            select(DiscoveryLog.geo_location_id, func.max(DiscoveryLog.run_at))
            .group_by(DiscoveryLog.geo_location_id))).all())
        for agency in agencies:
            cfg = discovery_settings(agency)
            if not cfg.get("enabled"):
                continue
            interval = timedelta(minutes=int(cfg.get("run_interval_minutes") or 60))
            geos = (await session.execute(select(GeoLocation).where(
                GeoLocation.agency_id == agency.id, GeoLocation.is_active.is_(True),
                GeoLocation.auto_discovery_enabled.is_(True)))).scalars().all()
            for geo in geos:
                if not geo.keywords:
                    continue  # the city's vocabulary is not generated yet
                last = last_runs.get(geo.id)
                # a few minutes of slack: the beat fires hourly, runs take minutes
                if last is None or now - last >= interval - timedelta(minutes=10):
                    due.append(str(geo.id))
    return due


@shared_task(name="worker.tasks.discovery.run_discovery_for_all_agencies")
def run_discovery_for_all_agencies() -> int:
    geo_ids = run_async(_due_geo_ids(datetime.now(timezone.utc)))
    for geo_id in geo_ids:
        run_discovery_for_geo.apply_async(args=[geo_id], queue=QUEUE)
    logger.info("Discovery dispatched", cities=len(geo_ids))
    return len(geo_ids)


async def _run_for_geo(geo_id: str, force: bool) -> dict:
    from app.services.discovery.scheduler import run_for_geo  # noqa: PLC0415

    report = await run_for_geo(geo_id, force=force)
    if report is None:
        return {"skipped": True}
    return {"found": report.found, "tested": report.tested, "activated": report.activated,
            "sandboxed": report.sandboxed, "rejected": report.rejected, "errors": report.errors}


@shared_task(name="worker.tasks.discovery.run_discovery_for_geo",
             soft_time_limit=GEO_TIMEOUT + 20, time_limit=GEO_TIMEOUT + 40)
def run_discovery_for_geo(geo_id: str, force: bool = False) -> dict:
    return run_async(_run_for_geo(geo_id, force), timeout=GEO_TIMEOUT)


async def _check_source_health() -> dict:
    from sqlalchemy import select  # noqa: PLC0415

    from app.database import async_session  # noqa: PLC0415
    from app.models.source import Source  # noqa: PLC0415
    from app.services.billing import collectable_agency_ids  # noqa: PLC0415
    from app.services.discovery.clients import PlatformClients  # noqa: PLC0415
    from app.services.discovery.health import check_sources  # noqa: PLC0415

    async with async_session() as session:
        sources = (await session.execute(select(Source).where(
            Source.status.in_(("active", "sandbox")),
            Source.agency_id.in_(collectable_agency_ids()),
        ))).scalars().all()
        async with PlatformClients() as clients:
            counts = await check_sources(session, sources, clients)
    logger.info("Source health check", **counts)
    return counts


@shared_task(name="worker.tasks.discovery.check_source_health",
             soft_time_limit=GEO_TIMEOUT + 20, time_limit=GEO_TIMEOUT + 40)
def check_source_health() -> dict:
    return run_async(_check_source_health(), timeout=GEO_TIMEOUT)


@shared_task(name="worker.tasks.discovery.retry_sandbox_candidates",
             soft_time_limit=GEO_TIMEOUT + 20, time_limit=GEO_TIMEOUT + 40)
def retry_sandbox_candidates() -> dict:
    from app.services.discovery.scheduler import retry_due_candidates  # noqa: PLC0415

    return run_async(retry_due_candidates(), timeout=GEO_TIMEOUT)
