"""Matching Celery tasks. Runs the matching engine for a lead off the request path."""
from __future__ import annotations

import structlog
from celery import shared_task

from worker.async_runner import run_async

logger = structlog.get_logger()


@shared_task(name="worker.tasks.matching_tasks.run_matching_for_lead")
def run_matching_for_lead(lead_id: str, override_budget: int | None = None) -> int:
    from app.services.matching import MatchingEngine

    return run_async(MatchingEngine.run_for_new_lead(lead_id, override_budget=override_budget))


@shared_task(name="worker.tasks.matching_tasks.rematch_on_price_change")
def rematch_on_price_change(property_id: str, old_price: int, new_price: int) -> int:
    """Re-run matching for a property after its price dropped (TZ 32.4)."""
    from app.services.matching import MatchingEngine

    return run_async(MatchingEngine.rematch_on_price_change(property_id, old_price, new_price))


DROP_THRESHOLD = 0.05


async def _sweep_price_drops() -> int:
    """Catch price drops that never went through the API.

    TZ 32.4 re-matches on a drop of 5% or more, and the PATCH endpoint does that
    the moment a manager edits a price. Nothing covered the other ways a price
    changes -- a catalogue import, a CRM sync, an edit straight in the database --
    so the buyer whose budget the flat had just dropped into was never told.
    """
    from sqlalchemy import select

    from app.database import async_session
    from app.models.property import Property
    from app.services.matching import MatchingEngine

    rematched = 0
    async with async_session() as session:
        stmt = select(Property).where(
            Property.status == "active",
            Property.price.isnot(None),
            Property.last_rematch_price.isnot(None),
            Property.price < Property.last_rematch_price,
        )
        for prop in (await session.execute(stmt)).scalars().all():
            previous, current = prop.last_rematch_price, prop.price
            if not previous or (previous - current) / previous < DROP_THRESHOLD:
                continue
            await MatchingEngine.rematch_on_price_change(str(prop.id), previous, current)
            prop.last_rematch_price = current
            rematched += 1
        await session.commit()

    logger.info("Price drop sweep finished", properties=rematched)
    return rematched


@shared_task(name="worker.tasks.matching_tasks.sweep_price_drops")
def sweep_price_drops() -> int:
    return run_async(_sweep_price_drops())
