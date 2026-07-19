"""Tests for the matching engine: weighted scoring + run_for_new_lead."""
import os
from types import SimpleNamespace

import pytest

from app.services.matching import MATCH_THRESHOLD, calculate_match_score


def make_lead(**kw):
    base = dict(
        budget_min=None, budget_max=None, segment=None, geo_location_id=None,
        buyer_profile={}, urgency=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def make_prop(**kw):
    base = dict(price=None, target_segments=[], geo_location_id=None, ai_analysis={})
    base.update(kw)
    return SimpleNamespace(**base)


def test_budget_in_range_adds_30():
    lead = make_lead(budget_min=5_000_000, budget_max=8_000_000)
    prop = make_prop(price=7_000_000)
    assert calculate_match_score(lead, prop) == 30


def test_budget_far_over_penalized():
    lead = make_lead(budget_min=5_000_000, budget_max=8_000_000)
    prop = make_prop(price=20_000_000)  # > budget_max * 1.5
    assert calculate_match_score(lead, prop) == 0  # -15 clamped to 0


def test_segment_match_adds_25():
    lead = make_lead(segment="family")
    prop = make_prop(target_segments=["family", "investor"])
    assert calculate_match_score(lead, prop) == 25


def test_geo_match_adds_20():
    lead = make_lead(geo_location_id="g1")
    prop = make_prop(geo_location_id="g1")
    assert calculate_match_score(lead, prop) == 20


def test_both_geo_none_gives_no_bonus():
    # The TZ bug: None == None would have granted +20.
    lead = make_lead(geo_location_id=None)
    prop = make_prop(geo_location_id=None)
    assert calculate_match_score(lead, prop) == 0


def test_priorities_overlap_capped_at_15():
    lead = make_lead(buyer_profile={"priority_factors": ["Море", "Школа", "Парк", "Тишина"]})
    prop = make_prop(ai_analysis={"strengths": ["море", "школа", "парк", "тишина"]})
    assert calculate_match_score(lead, prop) == 15  # 4*5 capped at 15


def test_hot_urgency_adds_10():
    assert calculate_match_score(make_lead(urgency="hot"), make_prop()) == 10


def test_perfect_score_is_100():
    lead = make_lead(
        budget_min=5_000_000, budget_max=8_000_000, segment="family",
        geo_location_id="g1", urgency="hot",
        buyer_profile={"priority_factors": ["море", "школа", "парк"]},
    )
    prop = make_prop(
        price=7_000_000, target_segments=["family"], geo_location_id="g1",
        ai_analysis={"strengths": ["море", "школа", "парк"]},
    )
    assert calculate_match_score(lead, prop) == 100


def test_threshold_constant():
    assert MATCH_THRESHOLD == 60


# --- gated DB integration ---

@pytest.mark.skipif(os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL")
@pytest.mark.asyncio
async def test_run_for_new_lead_creates_matches(monkeypatch):
    from sqlalchemy import select

    from app.database import async_session, engine, run_migrations
    from app.models.agency import Agency
    from app.models.geo_location import GeoLocation
    from app.models.lead import Lead
    from app.models.match import LeadPropertyMatch
    from app.models.property import Property
    from app.services.ai_service import AIService
    from app.services.matching import MatchingEngine

    async def fake_complete(self, system, user, module, agency_id="global"):
        return '{"pitch_text": "Отличный вариант у моря", "match_highlights": ["море"]}'

    monkeypatch.setattr(AIService, "complete", fake_complete)

    await run_migrations()
    try:
        async with async_session() as s:
            agency = Agency(name="Match Agency", base_city="Геленджик")
            s.add(agency)
            await s.flush()
            geo = GeoLocation(agency_id=agency.id, city_name="Геленджик", geo_type="base")
            s.add(geo)
            await s.flush()
            # A matching property (budget + geo + segment) and a too-expensive one.
            s.add(Property(agency_id=agency.id, geo_location_id=geo.id, title="2к у моря",
                           price=7_000_000, status="active", target_segments=["family"]))
            s.add(Property(agency_id=agency.id, geo_location_id=geo.id, title="Дорогой пентхаус",
                           price=90_000_000, status="active", target_segments=["investor"]))
            lead = Lead(agency_id=agency.id, geo_location_id=geo.id, source_type="signal",
                        segment="family", budget_min=5_000_000, budget_max=8_000_000, urgency="hot")
            s.add(lead)
            await s.commit()
            lead_id = str(lead.id)

        created = await MatchingEngine.run_for_new_lead(lead_id)
        assert created >= 1

        async with async_session() as s:
            matches = (
                await s.execute(select(LeadPropertyMatch).where(LeadPropertyMatch.lead_id == lead_id))
            ).scalars().all()
            assert len(matches) == created
            assert all(m.match_score >= MATCH_THRESHOLD for m in matches)
            assert any(m.generated_pitch for m in matches)
    finally:
        await engine.dispose()
