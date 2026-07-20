"""Analytics router tests (need PostgreSQL). TZ section 32."""
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL"
)


@pytest.mark.asyncio
async def test_analytics_overview_funnel_and_source_roi():
    from app.database import async_session, run_migrations
    from app.dependencies import CurrentManager
    from app.models.agency import Agency
    from app.models.deal_outcome import DealOutcome
    from app.models.lead import Lead
    from app.models.property import Property
    from app.routers.analytics import (
        analytics_funnel,
        analytics_overview,
        analytics_source_roi,
    )

    await run_migrations()
    async with async_session() as s:
        agency = Agency(name="Analytics Agency", base_city="Сочи")
        s.add(agency)
        await s.flush()
        # Leads across the funnel + attribution.
        won_lead = Lead(agency_id=agency.id, source_type="lead_magnet", status="deal",
                        utm_source="vk")
        s.add(won_lead)
        s.add(Lead(agency_id=agency.id, source_type="lead_magnet", status="qualified",
                   utm_source="vk"))
        s.add(Lead(agency_id=agency.id, source_type="signal", status="new"))
        s.add(Lead(agency_id=agency.id, source_type="signal", status="in_progress"))
        s.add(Property(agency_id=agency.id, title="Кв", price=5_000_000, status="active"))
        await s.flush()
        s.add(DealOutcome(agency_id=agency.id, lead_id=won_lead.id, outcome="won",
                          commission_amount=300_000, deal_amount=5_000_000))
        await s.commit()
        agency_id = str(agency.id)

    current = CurrentManager(manager_id="m1", agency_id=agency_id)

    async with async_session() as s:
        ov = await analytics_overview(current=current, session=s)
        assert ov["total_leads"] == 4
        assert ov["active_properties"] == 1
        assert ov["deals_won"] == 1
        assert ov["total_commission"] == 300_000

    async with async_session() as s:
        funnel = await analytics_funnel(current=current, session=s)
        assert funnel["total"] == 4
        assert funnel["stages"]["deal"] == 1
        assert funnel["conversion"]["overall"] == 25.0

    async with async_session() as s:
        roi = await analytics_source_roi(current=current, session=s)
        vk = next(x for x in roi["sources"] if x["source"] == "vk")
        assert vk["leads"] == 2
        assert vk["deals_won"] == 1
        assert vk["commission"] == 300_000
