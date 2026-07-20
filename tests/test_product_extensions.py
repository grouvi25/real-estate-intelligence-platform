"""TZ section 32 product-extension tests (need PostgreSQL).

Covers the match feedback loop + exclusions, price-change rematch, lead-score
decay, overdue escalation and dead-source detection.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL"
)


async def _seed_agency_geo(s):
    from app.models.agency import Agency
    from app.models.geo_location import GeoLocation

    agency = Agency(name="Ext Agency", base_city="Геленджик")
    s.add(agency)
    await s.flush()
    geo = GeoLocation(agency_id=agency.id, city_name="Геленджик", geo_type="base")
    s.add(geo)
    await s.flush()
    return agency, geo


@pytest.mark.asyncio
async def test_match_feedback_creates_exclusion_and_blocks_rematch():
    from app.database import async_session, run_migrations
    from app.dependencies import CurrentManager
    from app.models.lead import Lead
    from app.models.match import LeadPropertyMatch
    from app.models.match_exclusion import MatchExclusion
    from app.models.property import Property
    from app.routers.leads import MatchFeedbackRequest, update_match_feedback
    from app.services.matching import MatchingEngine

    await run_migrations()
    async with async_session() as s:
        agency, geo = await _seed_agency_geo(s)
        lead = Lead(agency_id=agency.id, geo_location_id=geo.id, source_type="signal",
                    segment="family", status="new", budget_min=5_000_000, budget_max=8_000_000)
        s.add(lead)
        await s.flush()
        prop = Property(agency_id=agency.id, geo_location_id=geo.id, title="2к",
                        price=7_000_000, status="active", target_segments=["family"])
        s.add(prop)
        await s.flush()
        s.add(LeadPropertyMatch(lead_id=lead.id, property_id=prop.id, match_score=85,
                                status="suggested"))
        await s.commit()
        agency_id, lead_id, prop_id = str(agency.id), lead.id, prop.id

    current = CurrentManager(manager_id="m1", agency_id=agency_id)
    async with async_session() as s:
        res = await update_match_feedback(
            lead_id, prop_id,
            MatchFeedbackRequest(status="rejected", rejection_category="floor",
                                 rejection_reason="Первый этаж"),
            current=current, session=s,
        )
        assert res["status"] == "rejected"

    # exclusion recorded
    async with async_session() as s:
        excl = (await s.execute(
            select(MatchExclusion).where(MatchExclusion.lead_id == lead_id)
        )).scalars().all()
        assert len(excl) == 1
        assert excl[0].category == "floor"

    # matching engine must now skip the excluded property
    async with async_session() as s:
        lead = await s.get(Lead, lead_id)
        scored = await MatchingEngine.find_matches(s, lead, limit=5)
        assert all(str(p.id) != str(prop_id) for p, _ in scored)


@pytest.mark.asyncio
async def test_property_price_patch_queues_rematch(monkeypatch):
    from app.database import async_session, run_migrations
    from app.dependencies import CurrentManager
    from app.models.property import Property
    from app.routers.properties import UpdatePropertyRequest, update_property

    calls = {}
    import worker.tasks.matching_tasks as mt
    monkeypatch.setattr(mt.rematch_on_price_change, "delay",
                        lambda pid: calls.setdefault("pid", pid))

    await run_migrations()
    async with async_session() as s:
        agency, geo = await _seed_agency_geo(s)
        prop = Property(agency_id=agency.id, geo_location_id=geo.id, title="Студия",
                        price=5_000_000, area_total=40, status="active")
        s.add(prop)
        await s.commit()
        agency_id, prop_id = str(agency.id), prop.id

    current = CurrentManager(manager_id="m1", agency_id=agency_id)
    async with async_session() as s:
        res = await update_property(prop_id, UpdatePropertyRequest(price=4_500_000),
                                    current=current, session=s)
        assert res["price_changed"] is True
        assert res["price"] == 4_500_000
    assert calls.get("pid") == str(prop_id)

    # no price change -> no rematch
    calls.clear()
    async with async_session() as s:
        res = await update_property(prop_id, UpdatePropertyRequest(status="reserved"),
                                    current=current, session=s)
        assert res["price_changed"] is False
    assert "pid" not in calls


@pytest.mark.asyncio
async def test_rematch_property_creates_new_matches():
    from app.database import async_session, run_migrations
    from app.models.lead import Lead
    from app.models.match import LeadPropertyMatch
    from app.models.property import Property
    from app.services.matching import MatchingEngine

    await run_migrations()
    async with async_session() as s:
        agency, geo = await _seed_agency_geo(s)
        lead = Lead(agency_id=agency.id, geo_location_id=geo.id, source_type="signal",
                    segment="family", status="new", budget_min=4_000_000, budget_max=5_000_000)
        s.add(lead)
        prop = Property(agency_id=agency.id, geo_location_id=geo.id, title="3к",
                        price=4_800_000, status="active", target_segments=["family"])
        s.add(prop)
        await s.commit()
        prop_id, lead_id = prop.id, lead.id

    created = await MatchingEngine.rematch_property(str(prop_id))
    assert created == 1

    # idempotent: a second run does not duplicate
    created2 = await MatchingEngine.rematch_property(str(prop_id))
    assert created2 == 0

    async with async_session() as s:
        matches = (await s.execute(
            select(LeadPropertyMatch).where(LeadPropertyMatch.lead_id == lead_id)
        )).scalars().all()
        assert len(matches) == 1


@pytest.mark.asyncio
async def test_decay_lead_scores():
    from sqlalchemy import update

    from app.database import async_session, run_migrations
    from app.models.lead import Lead
    from worker.tasks.maintenance_tasks import _decay_lead_scores

    await run_migrations()
    async with async_session() as s:
        agency, geo = await _seed_agency_geo(s)
        lead = Lead(agency_id=agency.id, geo_location_id=geo.id, source_type="signal",
                    status="new", intent_score=100)
        s.add(lead)
        await s.commit()
        lead_id = lead.id
        # backdate updated_at beyond the decay window
        old = datetime.now(timezone.utc) - timedelta(days=10)
        await s.execute(update(Lead).where(Lead.id == lead_id).values(updated_at=old))
        await s.commit()

    changed = await _decay_lead_scores()
    assert changed >= 1
    async with async_session() as s:
        lead = await s.get(Lead, lead_id)
        assert lead.intent_score < 100


@pytest.mark.asyncio
async def test_escalate_overdue_leads():
    from sqlalchemy import update

    from app.database import async_session, run_migrations
    from app.models.task import Task
    from worker.tasks.maintenance_tasks import _escalate_overdue_leads

    await run_migrations()
    async with async_session() as s:
        agency, _ = await _seed_agency_geo(s)
        task = Task(agency_id=agency.id, task_type="contact", title="Контакт", status="pending")
        s.add(task)
        await s.commit()
        task_id = task.id
        old = datetime.now(timezone.utc) - timedelta(days=3)
        await s.execute(update(Task).where(Task.id == task_id).values(created_at=old))
        await s.commit()

    escalated = await _escalate_overdue_leads()
    assert escalated >= 1
    async with async_session() as s:
        task = await s.get(Task, task_id)
        assert task.is_urgent is True
        assert task.escalated_at is not None


@pytest.mark.asyncio
async def test_check_dead_sources():
    from sqlalchemy import update

    from app.database import async_session, run_migrations
    from app.models.source import Source
    from worker.tasks.maintenance_tasks import _check_dead_sources

    await run_migrations()
    async with async_session() as s:
        agency, _ = await _seed_agency_geo(s)
        src = Source(agency_id=agency.id, source_type="telegram_channel",
                     source_url="https://t.me/dead", status="active")
        s.add(src)
        await s.commit()
        src_id = src.id
        old = datetime.now(timezone.utc) - timedelta(days=30)
        await s.execute(update(Source).where(Source.id == src_id).values(
            created_at=old, last_checked_at=old))
        await s.commit()

    dead = await _check_dead_sources()
    assert dead >= 1
    async with async_session() as s:
        src = await s.get(Source, src_id)
        assert src.status == "dead"


@pytest.mark.asyncio
async def test_utm_captured_on_subscribe():
    from app.database import async_session, run_migrations
    from app.models.lead import Lead
    from app.routers.lead_magnets import LM6CalcRequest, LM6SubscribeRequest, lm6_subscribe

    await run_migrations()
    async with async_session() as s:
        agency, _ = await _seed_agency_geo(s)
        await s.commit()
        agency_id = agency.id

    req = LM6SubscribeRequest(
        calc_data=LM6CalcRequest(property_price=7_500_000, city="Геленджик"),
        agency_id=agency_id, contact_name="Пётр",
        contact_phone="+7 900 777-88-99", consent_given=True, consent_text="ok",
        utm_source="vk", utm_campaign="spring", utm_medium="cpc",
    )
    async with async_session() as s:
        res = await lm6_subscribe(req, session=s)
        lead_id = uuid.UUID(res["lead_id"])

    async with async_session() as s:
        lead = await s.get(Lead, lead_id)
        assert lead.utm_source == "vk"
        assert lead.utm_campaign == "spring"
        assert lead.buyer_profile.get("lm_source") == "lm6_roi"
