"""Geo-related Celery tasks. Keyword generation for a new geo (TZ 13.2 / 15.1)."""
from __future__ import annotations

from typing import Any

import structlog
from celery import shared_task

from worker.async_runner import run_async

logger = structlog.get_logger()


async def _generate_keywords_for_geo(geo_id: str, city_data: dict[str, Any]) -> bool:
    """Generate keywords via AI and persist them onto the GeoLocation row."""
    from app.database import async_session
    from app.discovery.keyword_builder import generate_geo_keywords
    from app.models.geo_location import GeoLocation

    keywords = await generate_geo_keywords(city_data)
    async with async_session() as session:
        geo = await session.get(GeoLocation, geo_id)
        if geo is None:
            logger.warning("Geo not found for keyword generation", geo_id=geo_id)
            return False
        geo.keywords = keywords
        await session.commit()
    logger.info("Geo keywords generated", geo_id=geo_id)
    return True


@shared_task(name="worker.tasks.geo_tasks.generate_keywords_for_geo")
def generate_keywords_for_geo(geo_id: str, city_data: dict) -> bool:
    return run_async(_generate_keywords_for_geo(geo_id, city_data))
