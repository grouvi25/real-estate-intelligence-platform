"""Daily report tests (TZ 27.1). Formatter is pure; aggregation is DB-gated."""
import os

import pytest


def test_format_report_text_pure():
    from app.services.report_generator import format_report_text

    data = {
        "signals": {"total": 12, "hot": 3, "warm": 5, "top_segment": "family",
                    "top_geo": "Геленджик", "by_segment": {}, "by_city": {}},
        "leads": {"new": 4, "no_contact_over_24h": 2},
        "sources": {"active": 6, "sandbox": 1},
    }
    text = format_report_text("Агентство Море", data)
    assert "Агентство Море" in text
    assert "Сигналы: 12" in text
    assert "family" in text
    assert "ждут первого контакта" in text  # no_contact > 0 warning


def test_format_report_no_warning_when_all_contacted():
    from app.services.report_generator import format_report_text

    data = {
        "signals": {"total": 0, "hot": 0, "warm": 0, "top_segment": None,
                    "top_geo": None, "by_segment": {}, "by_city": {}},
        "leads": {"new": 0, "no_contact_over_24h": 0},
        "sources": {"active": 0, "sandbox": 0},
    }
    text = format_report_text("X", data)
    assert "ждут первого контакта" not in text


@pytest.mark.skipif(os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL")
@pytest.mark.asyncio
async def test_build_daily_report_aggregates():
    from app.database import async_session, run_migrations
    from app.models.agency import Agency
    from app.models.geo_location import GeoLocation
    from app.models.lead import Lead
    from app.models.signal import Signal
    from app.services.report_generator import build_daily_report

    await run_migrations()
    async with async_session() as s:
        agency = Agency(name="Report Agency", base_city="Геленджик")
        s.add(agency)
        await s.flush()
        geo = GeoLocation(agency_id=agency.id, city_name="Геленджик", geo_type="base")
        s.add(geo)
        await s.flush()
        s.add(Signal(agency_id=agency.id, geo_location_id=geo.id, raw_text="ищу 2к",
                     urgency="hot", segment="family"))
        s.add(Signal(agency_id=agency.id, geo_location_id=geo.id, raw_text="инвест",
                     urgency="warm", segment="investor"))
        s.add(Lead(agency_id=agency.id, source_type="signal", status="new"))
        await s.commit()
        agency_id = agency.id

    async with async_session() as s:
        data = await build_daily_report(s, agency_id)
    assert data["signals"]["total"] == 2
    assert data["signals"]["hot"] == 1
    assert data["signals"]["top_geo"] == "Геленджик"
    assert data["leads"]["new"] == 1
