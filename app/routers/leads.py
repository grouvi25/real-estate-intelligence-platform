"""Leads router: list, card (with matches), status update. TZ manifest routers/leads.py.

All endpoints require a manager JWT and are scoped to that manager's agency.
PII (name/phone) is decrypted only here, for authorized managers.
"""
from __future__ import annotations

import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from app.database import get_session
from app.dependencies import CurrentManager, get_current_manager
from app.exceptions import NotFoundError, ValidationError
from app.models.lead import Lead
from app.models.match import LeadPropertyMatch
from app.models.property import Property

logger = structlog.get_logger()
router = APIRouter()

LEAD_STATUSES = {"new", "in_progress", "qualified", "deal", "rejected", "archived", "referred"}
MAX_PAGE = 200


class UpdateStatusRequest(BaseModel):
    status: str
    rejection_reason: Optional[str] = None


def _lead_summary(lead: Lead) -> dict:
    return {
        "id": str(lead.id),
        "name": lead.name,
        "phone": lead.phone,
        "telegram_username": lead.telegram_username,
        "segment": lead.segment,
        "status": lead.status,
        "intent_score": lead.intent_score,
        "budget_min": lead.budget_min,
        "budget_max": lead.budget_max,
        "urgency": lead.urgency,
        "created_at": lead.created_at.isoformat(),
    }


@router.get("")
async def list_leads(
    status: Optional[str] = None,
    segment: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    limit = min(max(limit, 1), MAX_PAGE)
    offset = max(offset, 0)

    stmt = select(Lead).where(Lead.agency_id == uuid.UUID(current.agency_id))
    if status is not None:
        stmt = stmt.where(Lead.status == status)
    if segment is not None:
        stmt = stmt.where(Lead.segment == segment)
    stmt = stmt.order_by(Lead.created_at.desc()).limit(limit).offset(offset)

    rows = (await session.execute(stmt)).scalars().all()
    return {"count": len(rows), "leads": [_lead_summary(lead) for lead in rows]}


async def _get_scoped_lead(lead_id: uuid.UUID, current: CurrentManager, session) -> Lead:
    lead = await session.get(Lead, lead_id)
    if lead is None or str(lead.agency_id) != current.agency_id:
        raise NotFoundError("Lead", str(lead_id))
    return lead


@router.get("/{lead_id}")
async def get_lead(
    lead_id: uuid.UUID,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    lead = await _get_scoped_lead(lead_id, current, session)

    mstmt = (
        select(LeadPropertyMatch, Property)
        .join(Property, LeadPropertyMatch.property_id == Property.id)
        .where(LeadPropertyMatch.lead_id == lead_id)
        .order_by(LeadPropertyMatch.match_score.desc())
    )
    matches = [
        {
            "property_id": str(prop.id),
            "title": prop.title,
            "price": prop.price,
            "match_score": match.match_score,
            "pitch": match.generated_pitch,
            "status": match.status,
        }
        for match, prop in (await session.execute(mstmt)).all()
    ]

    card = _lead_summary(lead)
    card.update(
        {
            "email": lead.email,
            "source_type": lead.source_type,
            "source_platform": lead.source_platform,
            "purchase_goal": lead.purchase_goal,
            "lead_type": lead.lead_type,
            "buyer_profile": lead.buyer_profile,
            "consent_given": lead.consent_given,
            "signal_id": str(lead.signal_id) if lead.signal_id else None,
            "matches": matches,
        }
    )
    return card


@router.patch("/{lead_id}/status")
async def update_lead_status(
    lead_id: uuid.UUID,
    req: UpdateStatusRequest,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    if req.status not in LEAD_STATUSES:
        raise ValidationError("status", f"недопустимый статус: {req.status}")

    lead = await _get_scoped_lead(lead_id, current, session)
    lead.status = req.status
    if req.rejection_reason is not None:
        lead.rejection_reason = req.rejection_reason
    await session.commit()
    return {"id": str(lead.id), "status": lead.status}


@router.post("/{lead_id}/process-alternative", status_code=201)
async def process_alternative(
    lead_id: uuid.UUID,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """Sell-to-buy: create sell+buy tasks and re-run matching by target budget."""
    lead = await _get_scoped_lead(lead_id, current, session)
    if lead.lead_type != "alternative":
        raise ValidationError("lead_type", "лид не является альтернативным")

    from app.services.alternative_lead import build_alternative_tasks

    tasks, target_budget = build_alternative_tasks(lead)
    for task in tasks:
        session.add(task)
    await session.commit()

    from worker.tasks.matching_tasks import run_matching_for_lead

    run_matching_for_lead.delay(str(lead.id), target_budget)
    return {"tasks_created": len(tasks), "target_budget": target_budget}
