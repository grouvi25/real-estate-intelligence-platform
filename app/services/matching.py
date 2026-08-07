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


async def excluded_property_ids(session, lead_id) -> set:
    """Property ids a manager rejected for this lead — from the match_exclusions
    table (migration 005). Returned as strings for uniform comparison."""
    from app.models.match_exclusion import MatchExclusion

    stmt = select(MatchExclusion.property_id).where(MatchExclusion.lead_id == lead_id)
    return {str(pid) for pid in (await session.execute(stmt)).scalars().all()}


def profile_excluded_ids(lead) -> set:
    """Property ids excluded via buyer_profile.match_exclusions (TZ 32.5)."""
    profile = getattr(lead, "buyer_profile", None) or {}
    return {str(e.get("property_id")) for e in profile.get("match_exclusions", []) if e.get("property_id")}


async def all_excluded_ids(session, lead) -> set:
    """Union of table-based and profile-based exclusions (as strings)."""
    table_ids = await excluded_property_ids(session, lead.id) if lead.id else set()
    return table_ids | profile_excluded_ids(lead)


# Weights from TZ 16.2. They are the starting point, not the last word: the
# Knowledge Moat (TZ 21) recomputes them from the agency's own closed deals every
# Sunday and stores them on the agency. Until this read them back, that loop was
# open -- the moat learned every week and nothing ever used what it learned.
BASE_WEIGHTS: dict[str, int] = {
    "budget": 30,
    "segment": 25,
    "location": 20,
    "priorities": 15,
    "urgency": 10,
}
# A learned weight is a nudge, not a rewrite: one unusual quarter must not be
# able to make budget irrelevant.
WEIGHT_MIN, WEIGHT_MAX = 5, 45


def resolve_weights(agency_settings: Any = None) -> dict[str, int]:
    """Base weights, overridden by what the agency's own deals taught."""
    weights = dict(BASE_WEIGHTS)
    learned = (agency_settings or {}).get("knowledge_moat_weights") or {}
    for key in BASE_WEIGHTS:
        value = learned.get(f"{key}_weight", learned.get(key))
        if isinstance(value, (int, float)) and value > 0:
            # Stored either as a share (0.3) or as points (30).
            points = value * 100 if value <= 1 else value
            weights[key] = int(max(WEIGHT_MIN, min(WEIGHT_MAX, round(points))))
    return weights


async def agency_weights(session, agency_id) -> dict[str, int]:
    """Weights for this agency: what its own closed deals taught, else the base."""
    from app.models.agency import Agency  # noqa: PLC0415

    agency = await session.get(Agency, agency_id)
    return resolve_weights(agency.settings if agency else None)


def calculate_match_score(lead: Any, prop: Any, weights: Any = None) -> int:
    """Weighted 0-100 score for how well a property fits a lead."""
    w = weights if isinstance(weights, dict) else BASE_WEIGHTS
    score = 0

    budget_min = lead.budget_min or 0
    budget_max = lead.budget_max or 0
    price = prop.price or 0
    if budget_min <= price <= budget_max and budget_max > 0:
        score += w.get("budget", 30)
    elif price and budget_max and (price < budget_min * 1.2 or price > budget_max * 1.5):
        score -= 15

    if lead.segment and prop.target_segments and lead.segment in prop.target_segments:
        score += w.get("segment", 25)

    if lead.geo_location_id is not None and lead.geo_location_id == prop.geo_location_id:
        score += w.get("location", 20)

    if lead.buyer_profile and prop.ai_analysis:
        priorities = lead.buyer_profile.get("priority_factors", []) or []
        strengths = prop.ai_analysis.get("strengths", []) or []
        overlap = len({p.lower() for p in priorities} & {s.lower() for s in strengths})
        score += min(w.get("priorities", 15), overlap * 5)

    if lead.urgency == "hot":
        score += w.get("urgency", 10)

    return max(0, min(100, score))


async def generate_pitch(ai: Any, lead: Any, prop: Any) -> dict:
    """AI pitch for one pairing, per SYSTEM_PROMPT_MATCHING_PITCH.

    Shared with the lead magnet: LM-1 was assembling its pitch as a string —
    "2-комн., 7 900 000 ₽" — while the acceptance list (35.6) asks for this
    prompt, and the person on the other side got a price tag instead of a reason.
    """
    from app.prompts.pitch_generator import (  # noqa: PLC0415
        SYSTEM_PROMPT_MATCHING_PITCH,
        USER_PROMPT_PITCH,
    )
    from app.services.ai_service import safe_ai_parse  # noqa: PLC0415

    fallback = {"pitch_text": prop.title, "match_highlights": []}
    try:
        raw = await ai.complete(
            SYSTEM_PROMPT_MATCHING_PITCH,
            USER_PROMPT_PITCH.format(**_pitch_payload(lead, prop)),
            "matching_pitch",
            agency_id=str(lead.agency_id),
        )
        return safe_ai_parse(raw, fallback)
    except Exception as e:  # noqa: BLE001 - a pitch is worth less than the match
        logger.warning("Pitch generation failed", error=str(e), property_id=str(prop.id))
        return fallback


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
    async def find_matches(session, lead: Any, limit: int = 5, budget_max: Optional[int] = None):
        """Read-only: score active agency properties for a lead, return top matches.

        Returns a list of (Property, score) sorted by score desc. Used by the
        lead-magnet flow to show an immediate selection (no AI cost).
        """
        from app.models.property import Property

        stmt = select(Property).where(
            Property.agency_id == lead.agency_id, Property.status == "active"
        )
        if lead.geo_location_id is not None:
            stmt = stmt.where(Property.geo_location_id == lead.geo_location_id)
        properties = (await session.execute(stmt)).scalars().all()

        excluded = await all_excluded_ids(session, lead)
        weights = await agency_weights(session, lead.agency_id)

        cap = budget_max or lead.budget_max
        scored: list[tuple[Any, int]] = []
        for prop in properties:
            if str(prop.id) in excluded:
                continue  # manager rejected this pairing
            if cap and prop.price and prop.price > cap * 1.5:
                continue  # far over budget
            scored.append((prop, calculate_match_score(lead, prop, weights)))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:limit]

    @staticmethod
    async def run_for_new_lead(lead_id: str, override_budget: Optional[int] = None) -> int:
        """Score active properties in the lead's geo, persist matches >= threshold.

        Returns the number of matches created.
        """
        from app.database import async_session
        from app.models.lead import Lead
        from app.models.match import LeadPropertyMatch
        from app.models.property import Property
        from app.services.ai_service import AIService

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

            excluded = await all_excluded_ids(session, lead)
            properties = [p for p in properties if str(p.id) not in excluded]

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

            weights = await agency_weights(session, lead.agency_id)
            ai = AIService()
            try:
                for prop in properties:
                    score = calculate_match_score(scoring_lead, prop, weights)
                    if score < MATCH_THRESHOLD:
                        continue
                    pitch = await generate_pitch(ai, lead, prop)

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

    @staticmethod
    async def rematch_on_price_change(property_id: str, old_price: int, new_price: int) -> int:
        """Re-match a property against warm/hot leads after a price DROP (TZ 32.4).

        Targets leads whose budget_max now fits (new_price <= budget_max < old_price),
        creates/updates a suggested match with a price-drop pitch, and notifies the
        assigned manager. Templated pitch only (no AI cost on a background sweep).
        Returns the number of matches created or refreshed.
        """
        from app.database import async_session
        from app.models.lead import Lead
        from app.models.match import LeadPropertyMatch
        from app.models.property import Property
        from app.services.bot_abstraction import bot_layer

        touched = 0
        async with async_session() as session:
            prop = await session.get(Property, property_id)
            if prop is None:
                return 0

            leads = (await session.execute(
                select(Lead).where(
                    Lead.agency_id == prop.agency_id,
                    Lead.budget_max >= new_price,
                    Lead.budget_max < old_price,
                    Lead.status.in_(("new", "in_progress", "qualified")),
                    Lead.urgency.in_(("hot", "warm")),
                )
            )).scalars().all()

            drop_pct = int((old_price - new_price) / old_price * 100) if old_price else 0
            pitch = (
                f"Цена снижена: {old_price:,}₽ → {new_price:,}₽ "
                f"(-{drop_pct}%). Теперь в бюджете."
            ).replace(",", " ")

            for lead in leads:
                # all_excluded_ids, not profile_excluded_ids: rejections made from
                # the UI land in the match_exclusions table (migration 005), so
                # checking only buyer_profile re-offered a property the manager had
                # already turned down as soon as its price dropped.
                if str(prop.id) in await all_excluded_ids(session, lead):
                    continue
                existing = (await session.execute(
                    select(LeadPropertyMatch).where(
                        LeadPropertyMatch.lead_id == lead.id,
                        LeadPropertyMatch.property_id == prop.id)
                )).scalar_one_or_none()
                if existing:
                    existing.status = "suggested"
                    existing.generated_pitch = pitch
                else:
                    session.add(LeadPropertyMatch(
                        lead_id=lead.id, property_id=prop.id,
                        match_score=70, generated_pitch=pitch, status="suggested"))
                touched += 1
                if lead.assigned_to:
                    await bot_layer.notify_manager(
                        str(lead.assigned_to),
                        f"💰 {prop.title}: {old_price:,}₽ → {new_price:,}₽. "
                        f"Лид #{str(lead.id)[:6]} в бюджете!".replace(",", " "))
            await session.commit()

        logger.info("Rematch on price change", property_id=property_id, matches=touched)
        return touched
