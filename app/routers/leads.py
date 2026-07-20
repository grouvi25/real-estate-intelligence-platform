"""Leads router: list, card (with matches), status update. TZ manifest routers/leads.py.

All endpoints require a manager JWT and are scoped to that manager's agency.
PII (name/phone) is decrypted only here, for authorized managers.
"""
from __future__ import annotations

import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, Response
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
MATCH_STATUSES = {"suggested", "presented", "accepted", "rejected"}
# TZ 32.5 rejection categories.
REJECTION_CATEGORIES = {
    "price_too_high", "wrong_location", "wrong_size",
    "wrong_type", "client_changed_mind", "other",
}
MAX_PAGE = 200


class UpdateStatusRequest(BaseModel):
    status: str
    rejection_reason: Optional[str] = None


class MatchFeedbackRequest(BaseModel):
    status: str  # presented | accepted | rejected
    rejection_category: Optional[str] = None
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
    previous = lead.status
    lead.status = req.status
    if req.rejection_reason is not None:
        lead.rejection_reason = req.rejection_reason
    await session.commit()

    # Push newly qualified leads to the agency CRM (best-effort, off request path).
    if req.status == "qualified" and previous != "qualified":
        from worker.tasks.crm_tasks import export_lead_to_crm

        export_lead_to_crm.delay(str(lead.id))

    return {"id": str(lead.id), "status": lead.status}


@router.patch("/{lead_id}/matches/{property_id}")
async def update_match_feedback(
    lead_id: uuid.UUID,
    property_id: uuid.UUID,
    req: MatchFeedbackRequest,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """Record manager feedback on a suggested match (TZ 32 feedback loop).

    A rejection records the reason + category and writes a hard exclusion so the
    matching engine never re-suggests this property to this lead.
    """
    from datetime import datetime, timezone

    from app.models.match_exclusion import MatchExclusion

    if req.status not in MATCH_STATUSES:
        raise ValidationError("status", f"недопустимый статус: {req.status}")
    if req.rejection_category is not None and req.rejection_category not in REJECTION_CATEGORIES:
        raise ValidationError("rejection_category", f"недопустимая категория: {req.rejection_category}")

    lead = await _get_scoped_lead(lead_id, current, session)

    match = (
        await session.execute(
            select(LeadPropertyMatch).where(
                LeadPropertyMatch.lead_id == lead_id,
                LeadPropertyMatch.property_id == property_id,
            )
        )
    ).scalars().first()
    if match is None:
        raise NotFoundError("Match", f"{lead_id}/{property_id}")

    match.status = req.status
    if req.status == "rejected":
        match.rejection_reason = req.rejection_reason
        match.rejection_category = req.rejection_category
        match.feedback_given_at = datetime.now(timezone.utc)
        # Idempotent exclusion (UNIQUE lead_id, property_id).
        existing = (
            await session.execute(
                select(MatchExclusion).where(
                    MatchExclusion.lead_id == lead_id,
                    MatchExclusion.property_id == property_id,
                )
            )
        ).scalars().first()
        if existing is None:
            session.add(
                MatchExclusion(
                    agency_id=lead.agency_id, lead_id=lead_id, property_id=property_id,
                    category=req.rejection_category, reason=req.rejection_reason,
                )
            )
    await session.commit()
    logger.info("Match feedback", lead_id=str(lead_id), property_id=str(property_id),
                status=req.status)
    return {"lead_id": str(lead_id), "property_id": str(property_id), "status": match.status}


@router.post("/{lead_id}/matches/{property_id}/feedback")
async def match_feedback(
    lead_id: uuid.UUID,
    property_id: uuid.UUID,
    status: str,
    rejection_reason: Optional[str] = None,
    rejection_category: Optional[str] = None,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """TZ 32.5 match feedback: update the match and, on rejection, record the
    exclusion in buyer_profile.match_exclusions (last 20) so the matching engine
    never re-suggests this property to this lead."""
    from datetime import datetime, timezone

    if status not in MATCH_STATUSES:
        raise ValidationError("status", f"недопустимый статус: {status}")
    if rejection_category is not None and rejection_category not in REJECTION_CATEGORIES:
        raise ValidationError("rejection_category", f"недопустимая категория: {rejection_category}")

    lead = await _get_scoped_lead(lead_id, current, session)
    match = (
        await session.execute(
            select(LeadPropertyMatch).where(
                LeadPropertyMatch.lead_id == lead_id,
                LeadPropertyMatch.property_id == property_id,
            )
        )
    ).scalars().first()
    if match is None:
        raise NotFoundError("Match", f"{lead_id}/{property_id}")

    match.status = status
    match.rejection_reason = rejection_reason
    match.rejection_category = rejection_category
    match.feedback_given_at = datetime.now(timezone.utc)

    if status == "rejected" and rejection_category:
        profile = dict(lead.buyer_profile or {})
        excl = list(profile.get("match_exclusions", []))
        excl.append({"property_id": str(property_id), "reason": rejection_category,
                     "at": datetime.now(timezone.utc).isoformat()})
        profile["match_exclusions"] = excl[-20:]
        lead.buyer_profile = profile
    await session.commit()
    logger.info("Match feedback (TZ 32.5)", lead_id=str(lead_id), property_id=str(property_id),
                status=status)
    return {"status": "feedback_recorded", "match_status": match.status}


@router.get("/{lead_id}/document")
async def lead_commercial_offer(
    lead_id: uuid.UUID,
    format: str = "html",
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """Render a commercial offer (КП) with the lead's matched properties.

    ?format=html (default) or pdf. PDF needs the optional 'pdf' extra installed.
    """
    from app.services.document_service import render_html, render_pdf

    lead = await _get_scoped_lead(lead_id, current, session)
    mstmt = (
        select(LeadPropertyMatch, Property)
        .join(Property, LeadPropertyMatch.property_id == Property.id)
        .where(LeadPropertyMatch.lead_id == lead_id)
        .order_by(LeadPropertyMatch.match_score.desc())
    )
    properties = [
        {"title": prop.title, "price": prop.price, "match_score": match.match_score,
         "pitch": match.generated_pitch}
        for match, prop in (await session.execute(mstmt)).all()
    ]
    context = {
        "agency_name": "",
        "manager_name": "",
        "client_name": lead.name,
        "properties": properties,
    }
    if format == "pdf":
        pdf = render_pdf("commercial_offer", context)
        return Response(content=pdf, media_type="application/pdf")
    return HTMLResponse(content=render_html("commercial_offer", context))


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
