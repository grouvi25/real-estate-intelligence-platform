"""Tests for the LM-1 public lead magnet (property finder)."""
import os
import uuid

import pytest


@pytest.mark.asyncio
async def test_lm1_start_returns_session():
    from app.routers.lead_magnets import LM1Start, lm1_start

    res = await lm1_start(LM1Start())
    assert res["session_id"]
    assert res["next_step"] == "budget_and_city"


@pytest.mark.asyncio
async def test_lm1_requires_consent():
    from app.exceptions import ConsentRequiredError
    from app.routers.lead_magnets import LM1Result, lm1_submit

    req = LM1Result(
        agency_id=uuid.uuid4(), budget_max=8_000_000,
        contact_name="Иван", contact_phone="+79001234567", consent_given=False,
    )
    with pytest.raises(ConsentRequiredError):
        await lm1_submit(req, session=None)


@pytest.mark.skipif(os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL")
@pytest.mark.asyncio
async def test_lm1_creates_lead_matches_and_dedup():
    from sqlalchemy import select

    from app.database import async_session, run_migrations
    from app.models.agency import Agency
    from app.models.geo_location import GeoLocation
    from app.models.lead import Lead
    from app.models.property import Property
    from app.models.task import Task
    from app.routers.lead_magnets import LM1Result, lm1_submit
    from app.services.encryption import phone_blind_index

    await run_migrations()
    async with async_session() as s:
        agency = Agency(name="LM Agency", base_city="Геленджик")
        s.add(agency)
        await s.flush()
        geo = GeoLocation(agency_id=agency.id, city_name="Геленджик", geo_type="base")
        s.add(geo)
        await s.flush()
        # In budget and far over budget.
        s.add(Property(agency_id=agency.id, geo_location_id=geo.id, title="2к у моря", price=7_000_000, status="active"))
        s.add(Property(agency_id=agency.id, geo_location_id=geo.id, title="Пентхаус", price=90_000_000, status="active"))
        await s.commit()
        agency_id = agency.id

    phone = "+7 900 111-22-33"
    req = LM1Result(
        agency_id=agency_id, goal="own", budget_max=8_000_000,
        contact_name="Мария Иванова", contact_phone=phone,
        consent_given=True, consent_text="Согласие 152-ФЗ",
    )

    async with async_session() as s:
        res1 = await lm1_submit(req, session=s)
    assert res1["is_duplicate"] is False
    assert len(res1["matches"]) >= 1
    # The 90M property is far over budget -> excluded.
    assert all(m["price"] <= 8_000_000 * 1.5 for m in res1["matches"])
    lead_id = res1["lead_id"]

    async with async_session() as s:
        lead = await s.get(Lead, uuid.UUID(lead_id))
        assert lead.phone == phone  # decrypts
        assert lead.phone_hash == phone_blind_index(phone)
        tasks = (await s.execute(select(Task).where(Task.lead_id == lead.id))).scalars().all()
        assert len(tasks) == 1

    # Second submission with the same phone (different format) -> duplicate.
    req2 = LM1Result(
        agency_id=agency_id, budget_max=8_000_000,
        contact_name="Мария И.", contact_phone="+79001112233",
        consent_given=True, consent_text="Согласие",
    )
    async with async_session() as s:
        res2 = await lm1_submit(req2, session=s)
    assert res2["is_duplicate"] is True
    assert res2["lead_id"] == lead_id
