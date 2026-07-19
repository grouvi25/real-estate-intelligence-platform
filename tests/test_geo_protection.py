"""Geo protection tests (needs PostgreSQL: exercises migration 002 + partner logic)."""
import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL"
)


@pytest.mark.asyncio
async def test_allowed_when_region_open():
    from app.database import run_migrations
    from app.services.geo_protection import check_geo_protection

    await run_migrations()
    result = await check_geo_protection(f"OpenCity-{uuid.uuid4().hex[:8]}")
    assert result["decision"] == "allowed"


@pytest.mark.asyncio
async def test_blocked_when_protected_without_partner():
    from app.database import async_session, run_migrations
    from app.models.protected_geo import ProtectedGeo
    from app.services.geo_protection import check_geo_protection

    await run_migrations()
    city = f"BlockedCity-{uuid.uuid4().hex[:8]}"
    async with async_session() as s:
        s.add(ProtectedGeo(city_name=city, status="active", is_active=True))
        await s.commit()

    result = await check_geo_protection(city)
    assert result["decision"] == "blocked"
    assert result["partner_id"] is None


@pytest.mark.asyncio
async def test_partner_offer_when_active_partner():
    from app.database import async_session, run_migrations
    from app.models.agency import Agency
    from app.models.partner_agency import PartnerAgency
    from app.models.protected_geo import ProtectedGeo
    from app.services.geo_protection import check_geo_protection

    await run_migrations()
    city = f"PartnerCity-{uuid.uuid4().hex[:8]}"
    async with async_session() as s:
        agency = Agency(name="Owner", base_city="Геленджик")
        s.add(agency)
        await s.flush()
        partner = PartnerAgency(
            agency_id=agency.id, partner_name="Сочи Партнёр", partner_city="Сочи",
            commission_percent=30.0, is_active=True,
        )
        s.add(partner)
        await s.flush()
        s.add(ProtectedGeo(city_name=city, status="active", partner_agency_id=partner.id))
        await s.commit()
        partner_id = str(partner.id)

    result = await check_geo_protection(city)
    assert result["decision"] == "partner_offer"
    assert result["partner_id"] == partner_id
    assert "Сочи Партнёр" in result["reason"]
