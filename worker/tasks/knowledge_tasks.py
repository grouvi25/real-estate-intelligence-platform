"""Knowledge Moat Celery task. TZ section 21.2.

Weekly: recompute Source ROI (deterministic) and, when there is enough data,
AI-derived matching weights saved into agency.settings (best-effort).
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

import structlog
from celery import shared_task

from worker.async_runner import run_async

logger = structlog.get_logger()

AI_WEIGHTS_MIN_DEALS = 10


async def _recompute_ai_weights(session, deals) -> None:
    """Best-effort: ask AI for matching weights and store them per agency."""
    from app.models.agency import Agency
    from app.services.ai_service import AIService, safe_ai_parse

    ai = AIService()
    try:
        # The keys are fixed on purpose: matching.resolve_weights reads exactly
        # these, and free-form keys would be stored and silently ignored — which
        # is what happened while nothing read them at all.
        prompt = (
            f"Проанализируй {len(deals)} закрытых сделок агентства. Что сильнее всего "
            "предсказывало успешную сделку? Верни JSON строго с ключами "
            "budget_weight, segment_weight, location_weight, priorities_weight, "
            "urgency_weight — числа в баллах от 5 до 45, в сумме около 100."
        )
        res = await ai.complete("Ты — аналитик рынка недвижимости.", prompt, "daily_report")
        weights = safe_ai_parse(res, {
            "budget_weight": 30, "segment_weight": 25, "location_weight": 20,
            "priorities_weight": 15, "urgency_weight": 10,
        })
    finally:
        await ai.close()

    for agency_id in {d.agency_id for d in deals}:
        agency = await session.get(Agency, agency_id)
        if agency:
            settings = dict(agency.settings or {})
            settings["knowledge_moat_weights"] = weights
            agency.settings = settings


async def _update_knowledge_moat() -> dict:
    from sqlalchemy import select, update

    from app.database import async_session
    from app.models.deal_outcome import DealOutcome
    from app.models.source import Source

    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    async with async_session() as session:
        deals = (
            await session.execute(select(DealOutcome).where(DealOutcome.deal_closed_at > cutoff))
        ).scalars().all()

        # Source ROI: more deals -> higher score (capped).
        source_stats = Counter(d.source_id for d in deals if d.source_id)
        for source_id, count in source_stats.items():
            await session.execute(
                update(Source).where(Source.id == source_id).values(score=min(100, count * 10 + 20))
            )

        if len(deals) >= AI_WEIGHTS_MIN_DEALS:
            try:
                await _recompute_ai_weights(session, deals)
            except Exception as e:  # noqa: BLE001
                logger.warning("AI weight recompute failed", error=str(e))

        await session.commit()

    logger.info("Knowledge moat updated", deals=len(deals), sources_updated=len(source_stats))
    return {"deals": len(deals), "sources_updated": len(source_stats)}


@shared_task(name="worker.tasks.knowledge_tasks.update_knowledge_moat")
def update_knowledge_moat() -> dict:
    return run_async(_update_knowledge_moat())
