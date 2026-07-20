"""Knowledge Moat tests (needs PostgreSQL): record outcome, Source ROI, AI weights."""
import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL"
)


@pytest.mark.asyncio
async def test_record_outcome_endpoint():
    from app.database import async_session, run_migrations
    from app.dependencies import CurrentManager
    from app.models.agency import Agency
    from app.models.deal_outcome import DealOutcome
    from app.models.geo_location import GeoLocation
    from app.models.lead import Lead
    from app.models.signal import Signal
    from app.models.source import Source
    from app.routers.deals import RecordOutcomeRequest, record_outcome

    await run_migrations()
    async with async_session() as s:
        agency = Agency(name="KM Agency", base_city="Геленджик")
        s.add(agency)
        await s.flush()
        geo = GeoLocation(agency_id=agency.id, city_name="Геленджик", geo_type="base")
        s.add(geo)
        await s.flush()
        source = Source(agency_id=agency.id, geo_location_id=geo.id, source_type="telegram_chat",
                        source_url="https://t.me/x", status="active")
        s.add(source)
        await s.flush()
        signal = Signal(agency_id=agency.id, source_id=source.id, geo_location_id=geo.id, raw_text="ищу")
        s.add(signal)
        await s.flush()
        lead = Lead(agency_id=agency.id, geo_location_id=geo.id, signal_id=signal.id,
                    source_type="signal", segment="family", status="qualified")
        s.add(lead)
        await s.commit()
        agency_id, lead_id, source_id = agency.id, lead.id, source.id

    current = CurrentManager(manager_id="m1", agency_id=str(agency_id))
    async with async_session() as s:
        resp = await record_outcome(
            lead_id, RecordOutcomeRequest(outcome="deal_done", deal_amount=7_000_000),
            current=current, session=s,
        )
    assert resp["status"] == "outcome_recorded"

    async with async_session() as s:
        outcome = (await s.execute(select(DealOutcome).where(DealOutcome.lead_id == lead_id))).scalar_one()
        assert outcome.outcome == "deal_done"
        assert outcome.source_id == source_id  # traced back through the signal
        assert outcome.buyer_segment == "family"
        assert outcome.signal_to_lead_days is not None
        lead = await s.get(Lead, lead_id)
        assert lead.status == "deal"


@pytest.mark.asyncio
async def test_update_knowledge_moat_source_roi():
    from app.database import async_session, run_migrations
    from app.models.agency import Agency
    from app.models.deal_outcome import DealOutcome
    from app.models.source import Source
    from worker.tasks.knowledge_tasks import _update_knowledge_moat

    await run_migrations()
    async with async_session() as s:
        agency = Agency(name="ROI Agency", base_city="Геленджик")
        s.add(agency)
        await s.flush()
        source = Source(agency_id=agency.id, source_type="telegram_chat", source_url="https://t.me/roi", status="active", score=0)
        s.add(source)
        await s.flush()
        for _ in range(2):
            s.add(DealOutcome(agency_id=agency.id, source_id=source.id, outcome="deal_done",
                              deal_closed_at=datetime.now(timezone.utc)))
        await s.commit()
        source_id = source.id

    await _update_knowledge_moat()

    async with async_session() as s:
        source = await s.get(Source, source_id)
        assert source.score == 40  # 2 deals * 10 + 20


@pytest.mark.asyncio
async def test_update_knowledge_moat_ai_weights(monkeypatch):
    from app.database import async_session, run_migrations
    from app.models.agency import Agency
    from app.models.deal_outcome import DealOutcome
    from app.services.ai_service import AIService
    from worker.tasks.knowledge_tasks import _update_knowledge_moat

    async def fake_complete(self, system, user, module, agency_id="global"):
        return '{"segment_weight": 0.4, "budget_weight": 0.3}'

    monkeypatch.setattr(AIService, "complete", fake_complete)

    await run_migrations()
    async with async_session() as s:
        agency = Agency(name="Weights Agency", base_city="Геленджик")
        s.add(agency)
        await s.flush()
        for _ in range(10):
            s.add(DealOutcome(agency_id=agency.id, outcome="deal_done", buyer_segment="family",
                              deal_closed_at=datetime.now(timezone.utc)))
        await s.commit()
        agency_id = agency.id

    await _update_knowledge_moat()

    async with async_session() as s:
        agency = await s.get(Agency, agency_id)
        assert "knowledge_moat_weights" in (agency.settings or {})
        assert agency.settings["knowledge_moat_weights"]["segment_weight"] == 0.4
