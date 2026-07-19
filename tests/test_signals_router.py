"""Signals router tests (needs PostgreSQL): create-lead, generate-reply, list."""
import os

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL"
)


async def _make_agency_geo(session):
    from app.models.agency import Agency
    from app.models.geo_location import GeoLocation

    agency = Agency(name="Signals Agency", base_city="Геленджик")
    session.add(agency)
    await session.flush()
    geo = GeoLocation(agency_id=agency.id, city_name="Геленджик", geo_type="base")
    session.add(geo)
    await session.flush()
    return agency, geo


@pytest.mark.asyncio
async def test_create_lead_from_signal(monkeypatch):
    import worker.tasks.matching_tasks as mt
    from app.database import async_session, run_migrations
    from app.models.lead import Lead
    from app.models.signal import Signal
    from app.models.task import Task
    from app.routers.signals import CreateLeadRequest, create_lead_from_signal

    enqueued = []
    monkeypatch.setattr(mt.run_matching_for_lead, "delay", lambda *a, **k: enqueued.append(a))

    await run_migrations()
    async with async_session() as s:
        agency, geo = await _make_agency_geo(s)
        signal = Signal(
            agency_id=agency.id, geo_location_id=geo.id, raw_text="ищу 2к у моря до 8 млн",
            segment="family", intent_score=82, budget_min=5_000_000, budget_max=8_000_000,
            urgency="hot", status="new",
        )
        s.add(signal)
        await s.commit()
        signal_id = signal.id

    async with async_session() as s:
        resp = await create_lead_from_signal(
            signal_id, CreateLeadRequest(consent_text="Согласие 152-ФЗ", consent_ip="1.2.3.4"), session=s
        )
    assert resp["tasks_created"] == 1
    assert enqueued, "matching should be enqueued"

    async with async_session() as s:
        lead = (await s.execute(select(Lead).where(Lead.signal_id == signal_id))).scalar_one()
        assert lead.consent_given is True
        assert lead.consent_text == "Согласие 152-ФЗ"
        assert lead.segment == "family" and lead.intent_score == 82
        tasks = (await s.execute(select(Task).where(Task.lead_id == lead.id))).scalars().all()
        assert len(tasks) == 1 and tasks[0].task_type == "contact"
        sig = await s.get(Signal, signal_id)
        assert sig.status == "qualified"


@pytest.mark.asyncio
async def test_generate_reply(monkeypatch):
    from app.database import async_session, run_migrations
    from app.models.signal import Signal
    from app.routers.signals import generate_chat_reply
    from app.services.ai_service import AIService

    async def fake_complete(self, system, user, module, agency_id="global"):
        assert module == "reply_generator"
        return '{"reply_text": "В этом районе есть варианты, уточните бюджет", "tone": "expert"}'

    monkeypatch.setattr(AIService, "complete", fake_complete)
    await run_migrations()
    async with async_session() as s:
        agency, geo = await _make_agency_geo(s)
        signal = Signal(agency_id=agency.id, geo_location_id=geo.id, raw_text="ищу квартиру", status="new")
        s.add(signal)
        await s.commit()
        signal_id = signal.id

    async with async_session() as s:
        resp = await generate_chat_reply(signal_id, session=s)
    assert "reply_text" in resp["reply"]
    assert "бюджет" in resp["reply"]["reply_text"]


@pytest.mark.asyncio
async def test_list_signals_filters():
    from app.database import async_session, run_migrations
    from app.models.signal import Signal
    from app.routers.signals import list_signals

    await run_migrations()
    async with async_session() as s:
        agency, geo = await _make_agency_geo(s)
        s.add(Signal(agency_id=agency.id, geo_location_id=geo.id, raw_text="a", status="new", urgency="hot", intent_score=90))
        s.add(Signal(agency_id=agency.id, geo_location_id=geo.id, raw_text="b", status="new", urgency="cold", intent_score=30))
        s.add(Signal(agency_id=agency.id, geo_location_id=geo.id, raw_text="c", status="rejected", urgency="warm", intent_score=50))
        await s.commit()
        agency_id = agency.id

    async with async_session() as s:
        all_new = await list_signals(agency_id=agency_id, status="new", session=s)
        assert all_new["count"] == 2

        hot = await list_signals(agency_id=agency_id, min_intent_score=70, session=s)
        assert hot["count"] == 1
        assert hot["signals"][0]["intent_score"] == 90
