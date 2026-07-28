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
