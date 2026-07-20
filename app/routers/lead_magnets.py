"""Public lead magnets. TZ sections 17 + 29.5 (LM-1 property finder).

Public (no manager auth). The agency is identified by the landing page (agency_id
in the payload). 152-FZ consent checkbox is required. Phone dedup runs before
creating a lead. Matching is done synchronously with a templated pitch (no AI cost
on an unauthenticated endpoint, which the architect flagged as a budget risk).
"""
from __future__ import annotations

import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from app.database import get_session
from app.exceptions import ConsentRequiredError, NotFoundError
from app.models.agency import Agency
from app.models.lead import Lead
from app.models.match import LeadPropertyMatch
from app.models.task import Task
from app.services.rate_limit import rate_limit

logger = structlog.get_logger()
router = APIRouter()

VALID_GOALS = {"own", "invest", "rent_out", "relocate", "children"}


class LM1Start(BaseModel):
    session_id: Optional[str] = None
    goal: Optional[str] = None
    budget_max: Optional[int] = None


class LM1Result(BaseModel):
    agency_id: uuid.UUID
    session_id: Optional[str] = None
    goal: str = "own"
    budget_max: int
    contact_name: str
    contact_phone: str
    telegram_username: Optional[str] = None
    consent_given: bool = False
    consent_text: str = ""


def _pitch(prop) -> str:
    if prop.price:
        rooms = f"{prop.rooms}-комн., " if prop.rooms else ""
        return f"{rooms}{prop.price:,} ₽".replace(",", " ")
    return prop.title


@router.post("/property-finder/start")
async def lm1_start(req: LM1Start):
    """Initialize a property-finder session."""
    session_id = req.session_id or str(uuid.uuid4())
    return {"session_id": session_id, "next_step": "budget_and_city"}


@router.post(
    "/property-finder/result",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("lm_result", limit=10, window=60))],
)
async def lm1_submit(req: LM1Result, session=Depends(get_session)):
    """Save the lead (152-FZ consent), dedup by phone, return a matched selection."""
    if not req.consent_given:
        raise ConsentRequiredError()

    agency = await session.get(Agency, req.agency_id)
    if agency is None:
        raise NotFoundError("Agency", str(req.agency_id))

    from app.services.dedup_service import find_duplicate

    existing = await find_duplicate(session, req.agency_id, req.contact_phone)
    if existing is not None:
        return {"lead_id": str(existing.id), "is_duplicate": True, "matches": []}

    lead = Lead(
        agency_id=req.agency_id,
        source_type="lead_magnet",
        source_platform="web",
        purchase_goal=req.goal if req.goal in VALID_GOALS else "own",
        budget_max=req.budget_max,
        telegram_username=req.telegram_username,
        status="new",
        consent_given=True,
        consent_text=req.consent_text,
    )
    lead.name = req.contact_name
    lead.phone = req.contact_phone
    session.add(lead)
    await session.flush()

    from app.services.matching import MatchingEngine

    scored = await MatchingEngine.find_matches(session, lead, limit=5, budget_max=req.budget_max)
    matches = []
    for prop, score in scored:
        pitch = _pitch(prop)
        session.add(
            LeadPropertyMatch(
                lead_id=lead.id, property_id=prop.id, match_score=score,
                generated_pitch=pitch, status="suggested",
            )
        )
        matches.append(
            {"property_id": str(prop.id), "title": prop.title, "price": prop.price,
             "match_score": score, "pitch": pitch}
        )

    session.add(
        Task(
            agency_id=lead.agency_id, lead_id=lead.id, task_type="contact",
            title="Первый контакт (лид-магнит)", status="pending",
        )
    )
    await session.commit()

    logger.info("Lead magnet LM-1 submitted", lead_id=str(lead.id), matches=len(matches))
    return {"lead_id": str(lead.id), "is_duplicate": False, "matches": matches}
