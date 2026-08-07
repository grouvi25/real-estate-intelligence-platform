"""Public lead magnets. TZ sections 17 + 29 (LM-1..LM-6).

Public (no manager auth). The agency is identified by the landing page (agency_id
in the payload). 152-FZ consent is required for anything that captures PII; phone
dedup runs before creating a lead.

Rate limits follow the TZ: calculators/checkers 20/min, PII subscribe 5/min. We use
the project's Redis fixed-window limiter (app.services.rate_limit) rather than
slowapi, to avoid a dependency that duplicates existing infrastructure.

Endpoint names and response shapes match TZ section 29 exactly (acceptance tests
in TZ 33.2): /lm2/calculate, /lm2/subscribe, /lm3/analyze, /lm4/districts,
/lm6/calculate + subscribe variants.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from app.database import get_session
from app.exceptions import ConsentRequiredError, NotFoundError, ValidationError
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
    """Attribution tags forwarded by landing pages (TZ 32.6)."""

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


async def _create_lm_lead(
    session,
    *,
    agency_id: uuid.UUID,
    contact_name: str,
    contact_phone: str,
    consent_text: str,
    buyer_profile: dict,
    utm: UTMFields,
    telegram_username: Optional[str] = None,
    budget_max: Optional[int] = None,
    segment: Optional[str] = None,
) -> dict:
    """Shared subscribe helper: validate agency, dedup, create lead + task."""
    agency = await session.get(Agency, agency_id)
    if agency is None:
        raise NotFoundError("Agency", str(agency_id))

    existing = await find_duplicate(session, agency_id, contact_phone)
    if existing is not None:
        return {"lead_id": str(existing.id), "is_duplicate": True}

    lead = Lead(
        agency_id=agency_id,
        source_type="lead_magnet",
        source_platform="web",
        budget_max=budget_max,
        segment=segment,
        telegram_username=telegram_username,
        status="new",
        consent_given=True,
        consent_text=consent_text,
        consent_given_at=datetime.now(timezone.utc),
        buyer_profile=buyer_profile,
    )
    lead.name = contact_name
    lead.phone = contact_phone
    _apply_utm(lead, utm)
    session.add(lead)
    await session.flush()

    magnet = buyer_profile.get("lm_source", "lead_magnet")
    session.add(
        Task(
            agency_id=lead.agency_id, lead_id=lead.id, task_type="contact",
            title=f"Первый контакт (лид-магнит: {magnet})", status="pending",
        )
    )
    await session.commit()
    logger.info("Lead magnet subscribe", lead_id=str(lead.id), magnet=magnet)
    return {"lead_id": str(lead.id), "is_duplicate": False}


# ---------------------------------------------------------------------------
# LM-1: property finder (TZ 17 + 29.5).
# ---------------------------------------------------------------------------


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


@router.post("/lm1/start")
@router.post("/property-finder/start")
async def lm1_start(req: LM1Start):
    session_id = req.session_id or str(uuid.uuid4())
    return {"session_id": session_id, "next_step": "budget_and_city"}


@router.post(
    "/lm1/result",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("lm_result", limit=10, window=60))],
)
@router.post(
    # The name this endpoint has always had; the TZ (35.6) calls it /lm/lm1/result
    # and integrations may already use either.
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
        buyer_profile={"lm_source": "lm1_finder"},
    )
    lead.name = req.contact_name
    lead.phone = req.contact_phone
    _apply_utm(lead, req)
    session.add(lead)
    await session.flush()

    from app.services.ai_service import AIService
    from app.services.matching import MatchingEngine, generate_pitch

    scored = await MatchingEngine.find_matches(session, lead, limit=5, budget_max=req.budget_max)
    matches = []
    ai = AIService()
    try:
        for prop, score in scored:
            # The acceptance list (35.6) asks for the AI pitch here. It used to be
            # a formatted price — "2-комн., 7 900 000 ₽" — so the person filling
            # in the form got a price tag where a reason was promised.
            pitch = await generate_pitch(ai, lead, prop)
            text = pitch.get("pitch_text") or _pitch(prop)
            session.add(
                LeadPropertyMatch(
                    lead_id=lead.id, property_id=prop.id, match_score=score,
                    match_reasons=pitch.get("match_highlights", []),
                    generated_pitch=text, status="suggested",
                )
            )
            matches.append(
                {"property_id": str(prop.id), "title": prop.title, "price": prop.price,
                 "match_score": score, "pitch": text,
                 "highlights": pitch.get("match_highlights", [])}
            )
    finally:
        await ai.close()

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
# LM-2: mortgage calculator (TZ 29.1).
# ---------------------------------------------------------------------------


class LM2CalcRequest(BaseModel):
    property_price: int = Field(..., ge=500_000)
    down_payment: int = Field(..., ge=0)
    term_years: int = Field(default=20, ge=1, le=30)
    program: str = "standard"
    use_matkapital: bool = False
    monthly_income: Optional[int] = None


class LM2SubscribeRequest(UTMFields):
    calc_data: LM2CalcRequest
    contact_phone: str
    contact_name: str
    telegram_username: Optional[str] = None
    consent_given: bool = False
    consent_text: str = ""
    agency_id: uuid.UUID


@router.post(
    "/lm2/calculate",
    dependencies=[Depends(rate_limit("lm2_calc", limit=20, window=60))],
)
async def lm2_calculate(req: LM2CalcRequest):
    return {
        "selected_program": mortgage_calculator.calculate_mortgage(
            req.property_price, req.down_payment, req.term_years,
            req.program, req.use_matkapital, req.monthly_income),
        "all_programs": mortgage_calculator.compare_programs(
            req.property_price, req.down_payment, req.term_years),
    }


@router.post(
    "/lm2/subscribe",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("lm2_sub", limit=5, window=60))],
)
async def lm2_subscribe(req: LM2SubscribeRequest, session=Depends(get_session)):
    if not req.consent_given:
        raise ConsentRequiredError()
    calc = mortgage_calculator.calculate_mortgage(
        req.calc_data.property_price, req.calc_data.down_payment,
        req.calc_data.term_years, req.calc_data.program)
    res = await _create_lm_lead(
        session, agency_id=req.agency_id, contact_name=req.contact_name,
        contact_phone=req.contact_phone, consent_text=req.consent_text,
        telegram_username=req.telegram_username, budget_max=req.calc_data.property_price,
        buyer_profile={"lm_source": "lm2_mortgage", "calc_result": calc}, utm=req,
    )
    res["calc_result"] = calc
    return res


# ---------------------------------------------------------------------------
# LM-3: object check (TZ 29.2).
# ---------------------------------------------------------------------------


class LM3AnalyzeRequest(BaseModel):
    listing_url: Optional[str] = None
    listing_text: Optional[str] = None
    city: str


class LM3SubscribeRequest(UTMFields):
    listing_url: Optional[str] = None
    listing_text: Optional[str] = None
    city: str
    contact_phone: str
    contact_name: str
    consent_given: bool = False
    consent_text: str = ""
    agency_id: uuid.UUID


async def _analyze_listing(city: str, listing_url: Optional[str], listing_text: Optional[str]) -> dict:
    text = listing_text
    if listing_url and not text:
        ok, fetched = await object_checker.fetch_listing_text(listing_url)
        if not ok:
            return {"needs_manual_text": True, "message": fetched}
        text = fetched
    if not text or len(text) < 50:
        raise ValidationError("listing", "Необходимо предоставить текст или URL")

    from app.prompts.object_analysis import SYSTEM_PROMPT_OBJECT_ANALYSIS
    from app.services.ai_service import AIService, safe_ai_parse

    ai = AIService()
    try:
        resp = await ai.complete(
            SYSTEM_PROMPT_OBJECT_ANALYSIS,
            f"Проанализируй объявление в {city}:\n{text[:2500]}",
            "object_analysis",
        )
    finally:
        await ai.close()
    return {"analysis": safe_ai_parse(resp, {"strengths": [], "weaknesses": [], "risks": []})}


@router.post(
    "/lm3/analyze",
    dependencies=[Depends(rate_limit("lm3_analyze", limit=20, window=60))],
)
async def lm3_analyze(req: LM3AnalyzeRequest):
    result = await _analyze_listing(req.city, req.listing_url, req.listing_text)
    result["url"] = req.listing_url
    return result


@router.post(
    "/lm3/subscribe",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("lm3_sub", limit=5, window=60))],
)
async def lm3_subscribe(req: LM3SubscribeRequest, session=Depends(get_session)):
    if not req.consent_given:
        raise ConsentRequiredError()
    analysis: dict = {}
    text = req.listing_text
    if req.listing_url and not text:
        ok, fetched = await object_checker.fetch_listing_text(req.listing_url)
        text = fetched if ok else None
    if text and len(text) >= 50:
        try:
            res = await _analyze_listing(req.city, None, text)
            analysis = res.get("analysis", {})
        except Exception:  # noqa: BLE001
            analysis = {}
    out = await _create_lm_lead(
        session, agency_id=req.agency_id, contact_name=req.contact_name,
        contact_phone=req.contact_phone, consent_text=req.consent_text,
        buyer_profile={"lm_source": "lm3_checker", "checked_url": req.listing_url,
                       "ai_analysis": analysis}, utm=req,
    )
    out["analysis"] = analysis
    return out


# ---------------------------------------------------------------------------
# LM-4: district map (TZ 29.3).
# ---------------------------------------------------------------------------


class LM4DistrictsRequest(BaseModel):
    city: str
    scenario: str = Field(..., pattern="^(family|investor|relocant|remote|senior|vacationer)$")
    budget_max: Optional[int] = None


class LM4SubscribeRequest(UTMFields):
    city: str
    scenario: str
    budget_max: Optional[int] = None
    contact_phone: str
    contact_name: str
    consent_given: bool = False
    consent_text: str = ""
    agency_id: uuid.UUID


@router.post(
    "/lm4/districts",
    dependencies=[Depends(rate_limit("lm4_districts", limit=20, window=60))],
)
async def lm4_districts(req: LM4DistrictsRequest):
    """AI top-3 districts by life scenario; falls back to static data if AI is off."""
    from app.services.ai_service import AIService, safe_ai_parse

    budget_line = f"Бюджет до: {req.budget_max:,} ₽" if req.budget_max else "Бюджет: не указан"
    try:
        ai = AIService()
        try:
            resp = await ai.complete(
                districts_lm.SYSTEM_PROMPT_DISTRICTS,
                f"Город: {req.city}\nСценарий: {districts_lm.LIFE_SCENARIOS.get(req.scenario)}\n{budget_line}",
                "buyer_profile",
            )
        finally:
            await ai.close()
        parsed = safe_ai_parse(resp, {})
        if parsed.get("districts"):
            parsed["ai_used"] = True
            return parsed
    except Exception as e:  # noqa: BLE001
        logger.warning("LM-4 AI failed, using fallback", error=str(e))
    return districts_lm.fallback_districts(req.city, req.scenario)


@router.post(
    "/lm4/subscribe",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("lm4_sub", limit=5, window=60))],
)
async def lm4_subscribe(req: LM4SubscribeRequest, session=Depends(get_session)):
    if not req.consent_given:
        raise ConsentRequiredError()
    return await _create_lm_lead(
        session, agency_id=req.agency_id, contact_name=req.contact_name,
        contact_phone=req.contact_phone, consent_text=req.consent_text,
        budget_max=req.budget_max,
        buyer_profile={"lm_source": "lm4_districts", "scenario": req.scenario, "city": req.city},
        utm=req,
    )


# ---------------------------------------------------------------------------
# LM-6: investor ROI calculator (TZ 29.4).
# ---------------------------------------------------------------------------


class LM6CalcRequest(BaseModel):
    property_price: int = Field(..., ge=1_000_000)
    city: str
    down_payment: Optional[int] = None
    renovation_budget: int = 0
    monthly_expenses: int = 5_000


class LM6SubscribeRequest(UTMFields):
    calc_data: LM6CalcRequest
    contact_phone: str
    contact_name: str
    consent_given: bool = False
    consent_text: str = ""
    agency_id: uuid.UUID


@router.post(
    "/lm6/calculate",
    dependencies=[Depends(rate_limit("lm6_calc", limit=20, window=60))],
)
async def lm6_calculate(req: LM6CalcRequest):
    return roi_calculator.calculate_investment_roi(
        req.property_price, req.city, req.down_payment,
        req.renovation_budget, req.monthly_expenses)


@router.post(
    "/lm6/subscribe",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("lm6_sub", limit=5, window=60))],
)
async def lm6_subscribe(req: LM6SubscribeRequest, session=Depends(get_session)):
    if not req.consent_given:
        raise ConsentRequiredError()
    roi = roi_calculator.calculate_investment_roi(
        req.calc_data.property_price, req.calc_data.city, req.calc_data.down_payment)
    res = await _create_lm_lead(
        session, agency_id=req.agency_id, contact_name=req.contact_name,
        contact_phone=req.contact_phone, consent_text=req.consent_text,
        budget_max=req.calc_data.property_price, segment="investor",
        buyer_profile={"lm_source": "lm6_roi", "roi_result": roi, "city": req.calc_data.city},
        utm=req,
    )
    res["roi_result"] = roi
    return res
