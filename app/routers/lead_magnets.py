"""Public lead magnets. TZ sections 17 + 29 (LM-1..LM-6).

Public (no manager auth). The agency is identified by the landing page (agency_id
in the payload). 152-FZ consent checkbox is required for anything that captures
PII. Phone dedup runs before creating a lead. Matching is done synchronously with
a templated pitch (no AI cost on an unauthenticated endpoint, which the architect
flagged as a budget risk).

Rate limits follow the TZ: calculators/checkers 20/min, PII subscribe 5/min.
We use the project's Redis fixed-window limiter (app.services.rate_limit) instead
of slowapi to avoid adding a dependency that duplicates existing infrastructure.
"""
from __future__ import annotations

import uuid
from dataclasses import asdict
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
from app.services.dedup_service import find_duplicate
from app.services.lead_magnets import (
    districts as districts_lm,
    mortgage_calculator,
    object_checker,
    roi_calculator,
)
from app.services.rate_limit import rate_limit

logger = structlog.get_logger()
router = APIRouter()

VALID_GOALS = {"own", "invest", "rent_out", "relocate", "children"}


class UTMFields(BaseModel):
    """Attribution tags forwarded by landing pages (TZ 32)."""

    utm_source: Optional[str] = None
    utm_medium: Optional[str] = None
    utm_campaign: Optional[str] = None
    utm_content: Optional[str] = None
    utm_term: Optional[str] = None
    referrer: Optional[str] = None


def _apply_utm(lead: Lead, utm: UTMFields) -> None:
    lead.utm_source = utm.utm_source
    lead.utm_medium = utm.utm_medium
    lead.utm_campaign = utm.utm_campaign
    lead.utm_content = utm.utm_content
    lead.utm_term = utm.utm_term
    lead.referrer = utm.referrer


class LM1Start(BaseModel):
    session_id: Optional[str] = None
    goal: Optional[str] = None
    budget_max: Optional[int] = None


class LM1Result(UTMFields):
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
    _apply_utm(lead, req)
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


# ---------------------------------------------------------------------------
# Shared subscribe (PII capture) — used by LM-2/3/4/6.
# ---------------------------------------------------------------------------

VALID_MAGNETS = {"mortgage", "roi", "districts", "object_check"}


class MagnetSubscribe(UTMFields):
    agency_id: uuid.UUID
    magnet: str
    contact_name: str
    contact_phone: str
    telegram_username: Optional[str] = None
    budget_max: Optional[int] = None
    consent_given: bool = False
    consent_text: str = ""
    payload: dict = {}


async def _subscribe_magnet(req: MagnetSubscribe, session) -> dict:
    """Capture a lead from any calculator (152-FZ consent + phone dedup)."""
    if not req.consent_given:
        raise ConsentRequiredError()

    agency = await session.get(Agency, req.agency_id)
    if agency is None:
        raise NotFoundError("Agency", str(req.agency_id))

    magnet = req.magnet if req.magnet in VALID_MAGNETS else "mortgage"

    existing = await find_duplicate(session, req.agency_id, req.contact_phone)
    if existing is not None:
        return {"lead_id": str(existing.id), "is_duplicate": True}

    lead = Lead(
        agency_id=req.agency_id,
        source_type="lead_magnet",
        source_platform="web",
        budget_max=req.budget_max,
        telegram_username=req.telegram_username,
        status="new",
        consent_given=True,
        consent_text=req.consent_text,
        buyer_profile={"magnet": magnet, **(req.payload or {})},
    )
    lead.name = req.contact_name
    lead.phone = req.contact_phone
    _apply_utm(lead, req)
    session.add(lead)
    await session.flush()

    session.add(
        Task(
            agency_id=lead.agency_id, lead_id=lead.id, task_type="contact",
            title=f"Первый контакт (лид-магнит: {magnet})", status="pending",
        )
    )
    await session.commit()
    logger.info("Lead magnet subscribe", lead_id=str(lead.id), magnet=magnet)
    return {"lead_id": str(lead.id), "is_duplicate": False}


@router.post(
    "/subscribe",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("lm_subscribe", limit=5, window=60))],
)
async def magnet_subscribe(req: MagnetSubscribe, session=Depends(get_session)):
    """Shared subscribe endpoint for the LM-2/3/4/6 calculators."""
    return await _subscribe_magnet(req, session)


# ---------------------------------------------------------------------------
# LM-2: mortgage calculator (TZ 29.2).
# ---------------------------------------------------------------------------


class MortgageCalcRequest(BaseModel):
    price: int
    down_payment: int = 0
    term_years: int = 20
    region: str = "other"  # "msk_spb" | "other"
    use_matkapital: bool = False
    program: Optional[str] = None  # single program, or None to compare all


@router.post(
    "/mortgage/calculate",
    dependencies=[Depends(rate_limit("lm_mortgage", limit=20, window=60))],
)
async def mortgage_calculate(req: MortgageCalcRequest):
    """Compare mortgage programs (no PII, no persistence)."""
    if req.program:
        results = [
            mortgage_calculator.calculate_program(
                req.program, req.price, req.down_payment, req.term_years,
                req.region, req.use_matkapital,
            )
        ] if req.program in mortgage_calculator.MORTGAGE_PROGRAMS else []
    else:
        results = mortgage_calculator.compare_programs(
            req.price, req.down_payment, req.term_years, req.region, req.use_matkapital,
        )
    return {"matkapital": mortgage_calculator.MATKAPITAL_2026,
            "programs": [asdict(r) for r in results]}


# ---------------------------------------------------------------------------
# LM-3: object legal check (TZ 29.3).
# ---------------------------------------------------------------------------


class ObjectCheckRequest(BaseModel):
    url: str


@router.post(
    "/object-check/check",
    dependencies=[Depends(rate_limit("lm_object", limit=20, window=60))],
)
async def object_check(req: ObjectCheckRequest):
    """Return a legal due-diligence checklist for a listing URL."""
    return asdict(object_checker.check_object(req.url))


# ---------------------------------------------------------------------------
# LM-4: district recommender (TZ 29.4).
# ---------------------------------------------------------------------------


class DistrictsRequest(BaseModel):
    city: str
    scenario: str
    budget_max: Optional[int] = None
    area_sqm: Optional[float] = None


@router.post(
    "/districts/recommend",
    dependencies=[Depends(rate_limit("lm_districts", limit=20, window=60))],
)
async def districts_recommend(req: DistrictsRequest):
    """Rank a city's districts by life-scenario fit + budget."""
    recs = districts_lm.recommend_districts(
        req.city, req.scenario, req.budget_max, req.area_sqm
    )
    return {
        "scenarios": {k: v["name"] for k, v in districts_lm.LIFE_SCENARIOS.items()},
        "cities": list(districts_lm.DISTRICTS.keys()),
        "recommendations": [asdict(r) for r in recs],
    }


# ---------------------------------------------------------------------------
# LM-6: rental ROI calculator (TZ 29.6).
# ---------------------------------------------------------------------------


class RoiCalcRequest(BaseModel):
    price: int
    area_sqm: float
    city: str
    monthly_rent: Optional[int] = None


@router.post(
    "/roi/calculate",
    dependencies=[Depends(rate_limit("lm_roi", limit=20, window=60))],
)
async def roi_calculate(req: RoiCalcRequest):
    """Estimate rental yield, payback and deposit comparison (no PII)."""
    result = roi_calculator.calculate_roi(
        req.price, req.area_sqm, req.city, req.monthly_rent
    )
    return asdict(result)
