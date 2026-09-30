"""Celery: push a new lead into TopNLab. ТЗ «Интеграция с TopNLab» v1.0, раздел 6.

Runs off the request path: TopNLab being slow or down must never hold up the
manager who has just created the lead (ТЗ 10.2 — некритический путь). Only
TopnlabUnavailable is retried; a 422 means the data is wrong and a retry would
fail the same way.
"""
from __future__ import annotations

import structlog
from celery import shared_task

from worker.async_runner import run_async

logger = structlog.get_logger()

RETRY_COUNTDOWN = 60
MAX_RETRIES = 3


async def _sync(lead_id: str, force: bool) -> dict:
    from app.database import async_session
    from app.models.lead import Lead
    from app.services.topnlab_adapter import sync_lead_to_topnlab

    async with async_session() as session:
        lead = await session.get(Lead, lead_id)
        if lead is None:
            return {"exported": False, "reason": "not_found"}
        return await sync_lead_to_topnlab(session, lead, force=force)


@shared_task(name="worker.tasks.topnlab_sync.sync_lead_to_topnlab", bind=True,
             max_retries=MAX_RETRIES)
def sync_lead_to_topnlab(self, lead_id: str, agency_id: str | None = None,
                         force: bool = False) -> dict:
    """``agency_id`` is accepted as in ТЗ 6.1 but the lead already names it."""
    from app.services.topnlab_adapter import TopnlabUnavailable

    try:
        result = run_async(_sync(lead_id, force))
    except TopnlabUnavailable as exc:
        logger.warning("TopNLab sync will be retried", lead_id=lead_id,
                       attempt=self.request.retries + 1, error=str(exc))
        raise self.retry(exc=exc, countdown=RETRY_COUNTDOWN) from None
    logger.info("TopNLab sync finished", lead_id=lead_id, **{
        k: v for k, v in result.items() if k in ("exported", "reason", "topnlab_client_id")})
    return result


def queue_topnlab_sync(lead_id: str) -> None:
    """Enqueue the sync after a lead is committed. A broker hiccup must not fail
    lead creation; the lead goes out later when it is marked qualified."""
    from app.config import config

    if not config.topnlab_sync_enabled:
        return
    try:
        sync_lead_to_topnlab.delay(lead_id=lead_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to enqueue TopNLab sync", lead_id=lead_id, error=str(exc))
