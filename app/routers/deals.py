"""Deal outcomes router (Knowledge Moat input). TZ section 21.1.

Records the outcome of a lead into deal_outcomes with funnel metrics. Manager-scoped.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from app.database import get_session
from app.dependencies import CurrentManager, get_current_manager
from app.exceptions import NotFoundError, ValidationError
from app.models.deal_outcome import DealOutcome
from app.models.lead import Lead
from app.models.signal import Signal

logger = structlog.get_logger()
router = APIRouter()

VALID_OUTCOMES = {"deal_done", "rejected", "lost_to_competitor", "expired", "referral_deal"}


class RecordOutcomeRequest(BaseModel):
    outcome: str
    property_id: Optional[uuid.UUID] = None
    deal_amount: Optional[int] = None
    commission_amount: Optional[int] = None


@router.post("/{lead_id}/outcome", status_code=status.HTTP_201_CREATED)
async def record_outcome(
    lead_id: uuid.UUID,
    req: RecordOutcomeRequest,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    if req.outcome not in VALID_OUTCOMES:
        raise ValidationError("outcome", f"недопустимый исход: {req.outcome}")

    agency_uuid = uuid.UUID(current.agency_id)
    lead = await session.get(Lead, lead_id)
    if lead is None or lead.agency_id != agency_uuid:
        raise NotFoundError("Lead", str(lead_id))

    signal = await session.get(Signal, lead.signal_id) if lead.signal_id else None
    signal_to_lead_days = (lead.created_at - signal.created_at).days if signal else None

    outcome = DealOutcome(
        agency_id=lead.agency_id,
        lead_id=lead.id,
        property_id=req.property_id,
        source_id=signal.source_id if signal else None,
        manager_id=lead.assigned_to,
        geo_location_id=lead.geo_location_id,
        outcome=req.outcome,
        deal_amount=req.deal_amount,
        commission_amount=req.commission_amount,
        deal_closed_at=datetime.now(timezone.utc),
        buyer_segment=lead.segment,
        lead_magnet_used=lead.source_type,
        signal_to_lead_days=signal_to_lead_days,
    )
    session.add(outcome)
    if req.outcome == "deal_done":
        lead.status = "deal"
    await session.commit()

    # The CRM opened the deal; it should learn how it ended (addendum §4.1).
    from worker.tasks.crm_tasks import push_outcome_to_crm

    push_outcome_to_crm.delay(str(lead.id), str(outcome.id))

    logger.info("Deal outcome recorded", lead_id=str(lead_id), outcome=req.outcome)
    return {"status": "outcome_recorded", "outcome_id": str(outcome.id)}
