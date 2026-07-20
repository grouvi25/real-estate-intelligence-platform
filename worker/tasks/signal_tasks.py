"""Signal scoring Celery tasks. TZ sections 16.1 + 11.1 (intent-scoring-batch).

Stage 2 of intent scoring: pick up raw signals (status=new, not yet scored) —
e.g. produced by the Telegram collector — run the AI analysis and persist the
score/segment/urgency so managers see actionable, ranked signals.

No-op when no AI provider is configured (keeps the stand safe without keys).
"""
from __future__ import annotations

import asyncio
from typing import Optional

import structlog
from celery import shared_task

logger = structlog.get_logger()

VALID_SEGMENTS = {
    "family", "investor", "relocant", "remote_worker",
    "senior", "alternative", "student_parent", "not_buyer",
}
VALID_URGENCY = {"hot", "warm", "cold"}


def _as_int(value) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


async def _score_intent_batch(limit: Optional[int] = None) -> int:
    from sqlalchemy import select

    from app.config import config
    from app.database import async_session
    from app.models.signal import Signal
    from app.services.ai_service import AIService
    from app.services.intent_scoring import full_intent_analysis

    probe = AIService()
    configured = probe.provider_configured
    await probe.close()
    if not configured:
        logger.info("Intent scoring skipped: AI provider not configured")
        return 0

    batch = limit or config.ai_signal_batch_size
    scored = 0
    async with async_session() as session:
        stmt = (
            select(Signal)
            .where(Signal.status == "new", Signal.intent_score.is_(None))
            .order_by(Signal.created_at.asc())
            .limit(batch)
        )
        signals = (await session.execute(stmt)).scalars().all()
        for sig in signals:
            geo = sig.geo_location
            geo_profile = {
                "city_name": geo.city_name if geo else "",
                "agency_id": str(sig.agency_id),
            }
            message = {
                "text": sig.raw_text,
                "source_name": sig.source.source_name if sig.source else "Unknown",
            }
            try:
                data = await full_intent_analysis(message, geo_profile)
            except Exception as e:  # noqa: BLE001
                logger.warning("Intent scoring failed for signal", signal_id=str(sig.id), error=str(e))
                continue

            sig.intent_score = _as_int(data.get("intent_score")) or 0
            seg = data.get("segment")
            if seg in VALID_SEGMENTS:
                sig.segment = seg
            urg = data.get("urgency")
            if urg in VALID_URGENCY:
                sig.urgency = urg
            bmin, bmax = _as_int(data.get("budget_min")), _as_int(data.get("budget_max"))
            if bmin is not None:
                sig.budget_min = bmin
            if bmax is not None:
                sig.budget_max = bmax
            if data.get("location_interest"):
                sig.location_interest = data["location_interest"]
            sig.ai_analysis = data
            scored += 1
        await session.commit()
    logger.info("Intent scoring batch complete", scored=scored)
    return scored


@shared_task(name="worker.tasks.signal_tasks.score_intent_batch")
def score_intent_batch(limit: Optional[int] = None) -> int:
    return asyncio.run(_score_intent_batch(limit))
