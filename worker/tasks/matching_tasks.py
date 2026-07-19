"""Matching Celery tasks. Runs the matching engine for a lead off the request path."""
from __future__ import annotations

import asyncio

import structlog
from celery import shared_task

logger = structlog.get_logger()


@shared_task(name="worker.tasks.matching_tasks.run_matching_for_lead")
def run_matching_for_lead(lead_id: str) -> int:
    from app.services.matching import MatchingEngine

    return asyncio.run(MatchingEngine.run_for_new_lead(lead_id))
