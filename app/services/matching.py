"""Lead <-> Property matching engine. TZ section 16.2.

Weights (TZ): budget +30, segment +25, location +20, priorities +15, hot +10.
Fix vs. TZ: the location bonus required geo ids to be equal, which also matched
two NULL geos; now both must be non-null and equal.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional

import structlog
from sqlalchemy import select

logger = structlog.get_logger()

MATCH_THRESHOLD = 60


def calculate_match_score(lead: Any, prop: Any) -> int:
    """Weighted 0-100 score for how well a property fits a lead."""
    score = 0

    budget_min = lead.budget_min or 0
    budget_max = lead.budget_max or 0
    price = prop.price or 0
    if budget_min <= price <= budget_max and budget_max > 0:
        score += 30
    elif price and budget_max and (price < budget_min * 1.2 or price > budget_max * 1.5):
        score -= 15

    if lead.segment and prop.target_segments and lead.segment in prop.target_segments:
        score += 25

    if lead.geo_location_id is not None and lead.geo_location_id == prop.geo_location_id:
        score += 20

    if lead.buyer_profile and prop.ai_analysis:
        priorities = lead.buyer_profile.get("priority_factors", []) or []
        strengths = prop.ai_analysis.get("strengths", []) or []
        overlap = len({p.lower() for p in priorities} & {s.lower() for s in strengths})
        score += min(15, overlap * 5)

    if lead.urgency == "hot":
        score += 10

    return max(0, min(100, score))


def _pitch_payload(lead: Any, prop: Any) -> dict:
    profile = lead.buyer_profile or {}
    analysis = prop.ai_analysis or {}
    return {
        "segment": lead.segment or "",
        "purchase_goal": lead.purchase_goal or "own",
        "budget_min": lead.budget_min or 0,
        "budget_max": lead.budget_max or 0,
        "mortgage_type": profile.get("mortgage_type", "не указано"),
        "timeline": profile.get("purchase_timeline_months", "не указан"),
        "family": profile.get("family_composition", "не указано"),
        "priorities": ", ".join(profile.get("priority_factors", []) or []),
        "deal_breakers": ", ".join(profile.get("deal_breakers", []) or []),
        "emotional_profile": profile.get("emotional_profile", ""),
        "property_type": prop.property_type or "квартира",
        "address": prop.address or "",
        "price": prop.price or 0,
        "area": prop.area_total or "",
        "rooms": prop.rooms or "",
        "floor": prop.floor or "",
        "floors_total": prop.floors_total or "",
        "readiness_status": prop.readiness_status or "ready",
        "strengths": ", ".join(analysis.get("strengths", []) or []),
        "weaknesses": ", ".join(analysis.get("weaknesses", []) or []),
        "amenities": str(prop.amenities or []),
    }


class MatchingEngine:
    @staticmethod
    async def run_for_new_lead(lead_id: str, override_budget: Optional[int] = None) -> int:
        """Score active properties in the lead's geo, persist matches >= threshold.

        Returns the number of matches created.
        """
        from app.database import async_session
        from app.models.lead import Lead
        from app.models.match import LeadPropertyMatch
        from app.models.property import Property
        from app.prompts.pitch_generator import SYSTEM_PROMPT_MATCHING_PITCH, USER_PROMPT_PITCH
        from app.services.ai_service import AIService, safe_ai_parse

        created = 0
        async with async_session() as session:
            lead = await session.get(Lead, lead_id)
            if lead is None:
                return 0

            stmt = select(Property).where(
                Property.status == "active",
                Property.geo_location_id == lead.geo_location_id,
            )
            properties = (await session.execute(stmt)).scalars().all()
            if not properties:
                logger.info("Matching: no active properties in geo", lead_id=lead_id)
                return 0

            scoring_lead: Any = lead
            if override_budget is not None:
                scoring_lead = SimpleNamespace(
                    budget_min=lead.budget_min,
                    budget_max=override_budget,
                    segment=lead.segment,
                    geo_location_id=lead.geo_location_id,
                    buyer_profile=lead.buyer_profile,
                    urgency=lead.urgency,
                )

            ai = AIService()
            try:
                for prop in properties:
                    score = calculate_match_score(scoring_lead, prop)
                    if score < MATCH_THRESHOLD:
                        continue
                    try:
                        pitch_raw = await ai.complete(
                            SYSTEM_PROMPT_MATCHING_PITCH,
                            USER_PROMPT_PITCH.format(**_pitch_payload(lead, prop)),
                            "matching_pitch",
                            agency_id=str(lead.agency_id),
                        )
                        pitch = safe_ai_parse(pitch_raw, {"pitch_text": prop.title})
                    except Exception as e:  # noqa: BLE001
                        logger.warning("Pitch generation failed", error=str(e))
                        pitch = {"pitch_text": prop.title, "match_highlights": []}

                    session.add(
                        LeadPropertyMatch(
                            lead_id=lead.id,
                            property_id=prop.id,
                            match_score=score,
                            match_reasons=pitch.get("match_highlights", []),
                            generated_pitch=pitch.get("pitch_text", ""),
                            status="suggested",
                        )
                    )
                    created += 1
                await session.commit()
            finally:
                await ai.close()

        logger.info("Matching completed", lead_id=lead_id, matches_created=created)
        return created
