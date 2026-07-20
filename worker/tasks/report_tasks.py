"""Daily report Celery task. TZ section 27.1 (daily-report 07:30 MSK).

For each agency, aggregate the last 24h and deliver a summary to the owner (or
admin) via the bot layer. Runs off the request path; per-agency failures are
isolated so one bad agency doesn't abort the whole run.
"""
from __future__ import annotations

import asyncio

import structlog
from celery import shared_task

logger = structlog.get_logger()


async def _generate_daily_report() -> int:
    from sqlalchemy import select

    from app.database import async_session
    from app.models.agency import Agency
    from app.models.manager import Manager
    from app.services.bot_abstraction import bot_layer
    from app.services.report_generator import build_daily_report, format_report_text

    sent = 0
    async with async_session() as session:
        agencies = (await session.execute(select(Agency))).scalars().all()
        for agency in agencies:
            try:
                data = await build_daily_report(session, agency.id)
                text = format_report_text(agency.name, data)
                owner = (await session.execute(
                    select(Manager).where(
                        Manager.agency_id == agency.id,
                        Manager.role.in_(("owner", "admin")),
                        Manager.is_active.is_(True)).limit(1)
                )).scalar_one_or_none()
                if owner:
                    ok = await bot_layer.notify_manager(str(owner.id), text)
                    sent += 1 if ok else 0
            except Exception as e:  # noqa: BLE001
                logger.warning("Daily report failed for agency", agency_id=str(agency.id),
                               error=str(e))
    logger.info("Daily reports sent", count=sent)
    return sent


@shared_task(name="worker.tasks.report_tasks.generate_daily_report")
def generate_daily_report() -> int:
    return asyncio.run(_generate_daily_report())
