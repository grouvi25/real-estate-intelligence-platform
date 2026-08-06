"""Collector Celery tasks. TZ section 15 + Signal Bus.

Periodically pulls new messages from active Telegram sources through the
TelegramCollector, turning them into content_units + signals. No-op when no
Telethon session is configured.
"""
from __future__ import annotations

import structlog
from celery import shared_task

from worker.async_runner import run_async

logger = structlog.get_logger()


async def _collect_telegram_sources(limit_per_source: int = 50) -> int:
    from sqlalchemy import select

    from app.collectors.telegram_collector import TelegramCollector
    from app.database import async_session
    from app.models.geo_location import GeoLocation
    from app.models.source import Source

    collector = TelegramCollector()
    if not collector.is_available():
        logger.info("Telegram collector not configured; skipping")
        return 0

    total = 0
    try:
        async with async_session() as session:
            sources = (await session.execute(
                select(Source).where(
                    Source.status.in_(("active", "sandbox")),
                    Source.source_type.in_(("telegram_chat", "telegram_channel")),
                )
            )).scalars().all()
            for src in sources:
                keywords = {}
                if src.geo_location_id:
                    geo = await session.get(GeoLocation, src.geo_location_id)
                    keywords = (geo.keywords if geo else {}) or {}
                total += await collector.collect_from_source(
                    session, src, keywords, limit=limit_per_source)
    finally:
        await collector.close()
    logger.info("Telegram collection run complete", signals=total)
    return total


@shared_task(name="worker.tasks.collector_tasks.collect_telegram_sources")
def collect_telegram_sources(limit_per_source: int = 50) -> int:
    return run_async(_collect_telegram_sources(limit_per_source))


async def _collect_vk_sources(limit_per_source: int = 50) -> int:
    """Read VK groups the same way Telegram chats are read.

    Nothing called the VK API before this, so a vk_group source -- whether found
    by discovery or added by hand on the Источники screen -- was simply skipped
    and produced nothing, silently.
    """
    from sqlalchemy import select

    from app.collectors.vk_collector import VkCollector
    from app.database import async_session
    from app.models.geo_location import GeoLocation
    from app.models.source import Source

    collector = VkCollector()
    if not collector.is_available():
        logger.info("VK collector not configured; skipping")
        return 0

    total = 0
    try:
        async with async_session() as session:
            sources = (await session.execute(
                select(Source).where(
                    Source.status.in_(("active", "sandbox")),
                    Source.source_type == "vk_group",
                )
            )).scalars().all()
            for src in sources:
                keywords = {}
                if src.geo_location_id:
                    geo = await session.get(GeoLocation, src.geo_location_id)
                    keywords = (geo.keywords if geo else {}) or {}
                total += await collector.collect_from_source(
                    session, src, keywords, limit=limit_per_source)
    finally:
        await collector.close()
    logger.info("VK collection run complete", signals=total)
    return total


@shared_task(name="worker.tasks.collector_tasks.collect_vk_sources")
def collect_vk_sources(limit_per_source: int = 50) -> int:
    return run_async(_collect_vk_sources(limit_per_source))
