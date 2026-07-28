"""CRM export Celery tasks. TZ section 32.

Runs the outbound CRM webhook export off the request path so a slow or failing
CRM never blocks lead qualification.
"""
from __future__ import annotations

import structlog
from celery import shared_task

from worker.async_runner import run_async

logger = structlog.get_logger()


async def _export_lead(lead_id: str) -> dict:
    from app.database import async_session
    from app.models.lead import Lead
    from app.services.crm_export import export_lead_to_crm

    async with async_session() as session:
        lead = await session.get(Lead, lead_id)
        if lead is None:
            return {"exported": False, "reason": "not_found"}
        return await export_lead_to_crm(session, lead)


@shared_task(name="worker.tasks.crm_tasks.export_lead_to_crm")
def export_lead_to_crm(lead_id: str) -> dict:
    return run_async(_export_lead(lead_id))
