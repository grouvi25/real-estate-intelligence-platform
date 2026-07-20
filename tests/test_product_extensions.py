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
            MatchFeedbackRequest(status="rejected", rejection_category="wrong_size",
                                 rejection_reason="Мало комнат"),
            current=current, session=s,
        )
        assert res["status"] == "rejected"

    # exclusion recorded
    async with async_session() as s:
        excl = (await s.execute(
            select(MatchExclusion).where(MatchExclusion.lead_id == lead_id)
        )).scalars().all()
        assert len(excl) == 1
        assert excl[0].category == "wrong_size"

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
                        lambda pid, old, new: calls.update({"pid": pid, "old": old, "new": new}))

    await run_migrations()
    async with async_session() as s:
        agency, geo = await _seed_agency_geo(s)
        prop = Property(agency_id=agency.id, geo_location_id=geo.id, title="Студия",
                        price=5_000_000, area_total=40, status="active")
        s.add(prop)
        await s.commit()
        agency_id, prop_id = str(agency.id), prop.id

    current = CurrentManager(manager_id="m1", agency_id=agency_id)
    # 10% drop -> triggers rematch
    async with async_session() as s:
        res = await update_property(prop_id, UpdatePropertyRequest(price=4_500_000),
                                    current=current, session=s)
        assert res["price_changed"] is True
        assert res["price"] == 4_500_000
    assert calls.get("pid") == str(prop_id)
    assert calls.get("old") == 5_000_000 and calls.get("new") == 4_500_000

    # a <5% change or non-price update -> no rematch
    calls.clear()
    async with async_session() as s:
        res = await update_property(prop_id, UpdatePropertyRequest(status="reserved"),
                                    current=current, session=s)
        assert res["price_changed"] is False
    assert "pid" not in calls


@pytest.mark.asyncio
async def test_rematch_on_price_change_creates_matches(monkeypatch):
    from app.database import async_session, run_migrations
    from app.models.lead import Lead
    from app.models.match import LeadPropertyMatch
    from app.models.property import Property
    from app.services.matching import MatchingEngine

    # No network for the manager notification.
    import app.services.bot_abstraction as ba

    async def _noop(*a, **k):
        return True

    monkeypatch.setattr(ba.bot_layer, "notify_manager", _noop)

    await run_migrations()
    async with async_session() as s:
        agency, geo = await _seed_agency_geo(s)
        # budget_max 5.0M fits the [4.8M, 5.2M) drop window; urgency warm required.
        lead = Lead(agency_id=agency.id, geo_location_id=geo.id, source_type="signal",
                    segment="family", status="new", urgency="warm",
                    budget_min=4_000_000, budget_max=5_000_000)
        s.add(lead)
        prop = Property(agency_id=agency.id, geo_location_id=geo.id, title="3к",
                        price=4_800_000, status="active", target_segments=["family"])
        s.add(prop)
        await s.commit()
        prop_id, lead_id = prop.id, lead.id

    touched = await MatchingEngine.rematch_on_price_change(str(prop_id), 5_200_000, 4_800_000)
    assert touched == 1

    # idempotent: a second run refreshes the same match, not duplicates it
    touched2 = await MatchingEngine.rematch_on_price_change(str(prop_id), 5_200_000, 4_800_000)
    assert touched2 == 1

    async with async_session() as s:
        matches = (await s.execute(
            select(LeadPropertyMatch).where(LeadPropertyMatch.lead_id == lead_id)
        )).scalars().all()
        assert len(matches) == 1
        assert "снижена" in (matches[0].generated_pitch or "")


@pytest.mark.asyncio
async def test_decay_lead_urgency():
    from sqlalchemy import update

    from app.database import async_session, run_migrations
    from app.models.lead import Lead
    from worker.tasks.maintenance_tasks import _decay_lead_scores

    await run_migrations()
    async with async_session() as s:
        agency, geo = await _seed_agency_geo(s)
        lead = Lead(agency_id=agency.id, geo_location_id=geo.id, source_type="signal",
                    status="new", urgency="hot")
        s.add(lead)
        await s.commit()
        lead_id = lead.id
        # backdate beyond 48h so hot -> warm
        old = datetime.now(timezone.utc) - timedelta(hours=49)
        await s.execute(update(Lead).where(Lead.id == lead_id).values(updated_at=old))
        await s.commit()

    changed = await _decay_lead_scores()
    assert changed >= 1
    async with async_session() as s:
        lead = await s.get(Lead, lead_id)
        assert lead.urgency == "warm"


@pytest.mark.asyncio
async def test_escalate_overdue_leads_creates_task(monkeypatch):
    from sqlalchemy import select as sa_select
    from sqlalchemy import update

    from app.database import async_session, run_migrations
    from app.models.lead import Lead
    from app.models.task import Task
    from worker.tasks.maintenance_tasks import _escalate_overdue_leads

    import app.services.bot_abstraction as ba

    async def _noop(*a, **k):
        return True

    monkeypatch.setattr(ba.bot_layer, "notify_manager", _noop)

    await run_migrations()
    async with async_session() as s:
        agency, geo = await _seed_agency_geo(s)
        lead = Lead(agency_id=agency.id, geo_location_id=geo.id, source_type="signal",
                    status="new", urgency="hot", assigned_to=uuid.uuid4())
        s.add(lead)
        await s.commit()
        lead_id = lead.id
        old = datetime.now(timezone.utc) - timedelta(hours=48, minutes=10)
        await s.execute(update(Lead).where(Lead.id == lead_id).values(updated_at=old))
        await s.commit()

    actions = await _escalate_overdue_leads()
    assert actions >= 1
    async with async_session() as s:
        task = (await s.execute(
            sa_select(Task).where(Task.lead_id == lead_id, Task.task_type == "escalation")
        )).scalars().first()
        assert task is not None
        assert task.is_urgent is True


@pytest.mark.asyncio
async def test_check_dead_sources_pauses():
    from app.database import async_session, run_migrations
    from app.models.source import Source
    from worker.tasks.maintenance_tasks import _check_dead_sources

    await run_migrations()
    async with async_session() as s:
        agency, _ = await _seed_agency_geo(s)
        # No signals ever -> considered dead.
        src = Source(agency_id=agency.id, source_type="telegram_channel",
                     source_url="https://t.me/dead", source_name="dead chat", status="active")
        s.add(src)
        await s.commit()
        src_id = src.id

    dead = await _check_dead_sources()
    assert dead >= 1
    async with async_session() as s:
        src = await s.get(Source, src_id)
        assert src.status == "paused"


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


@pytest.mark.asyncio
async def test_dedup_by_telegram_username_and_all_sources():
    from app.database import async_session, run_migrations
    from app.models.lead import Lead
    from app.services.dedup_service import check_and_mark_duplicate, find_duplicate

    await run_migrations()
    async with async_session() as s:
        agency, _ = await _seed_agency_geo(s)
        lead = Lead(agency_id=agency.id, source_type="signal", status="new",
                    telegram_username="ivan_buyer")
        s.add(lead)
        await s.commit()
        agency_id, lead_id = agency.id, lead.id

    # find by @handle (with @) within window
    async with async_session() as s:
        found = await find_duplicate(s, agency_id, telegram_username="@ivan_buyer")
        assert found is not None and found.id == lead_id

    # check_and_mark merges the new source into all_sources
    async with async_session() as s:
        newcomer = Lead(agency_id=agency_id, source_type="lead_magnet", status="new",
                        telegram_username="ivan_buyer")
        existing, is_dup = await check_and_mark_duplicate(s, newcomer, "lm2_mortgage")
        assert is_dup is True
        assert existing.id == lead_id

    async with async_session() as s:
        lead = await s.get(Lead, lead_id)
        assert "lm2_mortgage" in lead.buyer_profile.get("all_sources", [])
