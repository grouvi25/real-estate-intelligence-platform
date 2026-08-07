"""Leads router tests (needs PostgreSQL): list, card+matches, status update, scoping."""
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL"
)


@pytest.mark.asyncio
async def test_leads_list_card_and_status(monkeypatch):
    from app.database import async_session, run_migrations
    from app.dependencies import CurrentManager
    from app.exceptions import NotFoundError, ValidationError
    from app.models.agency import Agency
    from app.models.geo_location import GeoLocation
    from app.models.lead import Lead
    from app.models.match import LeadPropertyMatch
    from app.models.property import Property
    from app.routers.leads import UpdateStatusRequest, get_lead, list_leads, update_lead_status

    await run_migrations()
    async with async_session() as s:
        agency = Agency(name="Leads Agency", base_city="Геленджик")
        s.add(agency)
        await s.flush()
        geo = GeoLocation(agency_id=agency.id, city_name="Геленджик", geo_type="base")
        s.add(geo)
        await s.flush()
        lead = Lead(agency_id=agency.id, geo_location_id=geo.id, source_type="lead_magnet",
                    segment="family", status="new", intent_score=75)
        lead.name = "Иван Петров"
        lead.phone = "+79001234567"
        s.add(lead)
        await s.flush()
        prop = Property(agency_id=agency.id, geo_location_id=geo.id, title="2к у моря", price=7_000_000, status="active")
        s.add(prop)
        await s.flush()
        s.add(LeadPropertyMatch(lead_id=lead.id, property_id=prop.id, match_score=85,
                                generated_pitch="Отличный вариант", status="suggested"))
        await s.commit()
        agency_id = str(agency.id)
        lead_id = lead.id

    current = CurrentManager(manager_id="m1", agency_id=agency_id)

    async with async_session() as s:
        listed = await list_leads(current=current, session=s)
        assert listed["count"] >= 1
        assert any(x["name"] == "Иван Петров" for x in listed["leads"])  # PII decrypted for manager

    async with async_session() as s:
        card = await get_lead(lead_id, current=current, session=s)
        assert card["phone"] == "+79001234567"
        assert len(card["matches"]) == 1
        assert card["matches"][0]["match_score"] == 85

    async with async_session() as s:
        res = await update_lead_status(lead_id, UpdateStatusRequest(status="qualified"), current=current, session=s)
        assert res["status"] == "qualified"

    # invalid status rejected
    async with async_session() as s:
        with pytest.raises(ValidationError):
            await update_lead_status(lead_id, UpdateStatusRequest(status="bogus"), current=current, session=s)

    # cross-agency access denied
    other = CurrentManager(manager_id="m2", agency_id="00000000-0000-4000-8000-000000000000")
    async with async_session() as s:
        with pytest.raises(NotFoundError):
            await get_lead(lead_id, current=other, session=s)


@pytest.mark.asyncio
async def test_leads_are_found_by_phone():
    """A 152-ФЗ request names a number, not a card id.

    The phone is encrypted at rest, so this has to go through the blind index --
    and it has to stay scoped to the agency like every other lead read.
    """
    from app.database import async_session, run_migrations
    from app.dependencies import CurrentManager
    from app.models.agency import Agency
    from app.models.lead import Lead
    from app.routers.leads import list_leads

    await run_migrations()
    async with async_session() as s:
        agency = Agency(name="Phone Lookup", base_city="Геленджик")
        s.add(agency)
        await s.flush()
        lead = Lead(agency_id=agency.id, source_type="manual", status="new")
        lead.name = "Анна Соколова"
        lead.phone = "+79181234567"
        s.add(lead)
        await s.commit()
        agency_id = str(agency.id)
        lead_id = lead.id

    current = CurrentManager(manager_id="m1", agency_id=agency_id)

    # Written the way a person writes it; the index normalises.
    async with async_session() as s:
        found = await list_leads(phone="+7 918 123-45-67", current=current, session=s)
        assert [x["id"] for x in found["leads"]] == [str(lead_id)]

    async with async_session() as s:
        missing = await list_leads(phone="+79990000000", current=current, session=s)
        assert missing["count"] == 0

    other = CurrentManager(manager_id="m2", agency_id="00000000-0000-4000-8000-000000000000")
    async with async_session() as s:
        assert (await list_leads(phone="+79181234567", current=other, session=s))["count"] == 0
