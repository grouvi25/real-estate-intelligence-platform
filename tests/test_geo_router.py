"""Tests for the geo router (create geo: allowed / blocked / partner_offer)."""
import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL"
)


def _noop_delay(monkeypatch):
    import worker.tasks.geo_tasks as gt

    calls = []
    monkeypatch.setattr(gt.generate_keywords_for_geo, "delay", lambda *a, **k: calls.append((a, k)))
    return calls


@pytest.mark.asyncio
async def test_create_geo_allowed(monkeypatch):
    from sqlalchemy import select

    from app.database import async_session, run_migrations
    from app.models.agency import Agency
    from app.models.geo_location import GeoLocation
    from app.models.protected_geo import ProtectedGeo
    from app.routers.geo import CreateGeoRequest, create_geo_location

    calls = _noop_delay(monkeypatch)
    await run_migrations()
    city = f"Новороссийск-{uuid.uuid4().hex[:8]}"
    async with async_session() as s:
        agency = Agency(name="Owner", base_city="Геленджик")
        s.add(agency)
        await s.commit()
        await s.refresh(agency)
        aid = agency.id

    async with async_session() as s:
        resp = await create_geo_location(aid, CreateGeoRequest(city_name=city, region="КК"), session=s)

    assert resp["status"] == "discovery_started"
    assert resp["geo_protected"] is True
    assert calls, "keyword generation task should be enqueued"

    async with async_session() as s:
        geos = (await s.execute(select(GeoLocation).where(GeoLocation.city_name == city))).scalars().all()
        assert len(geos) == 1 and geos[0].geo_type == "sales"
        prot = (await s.execute(select(ProtectedGeo).where(ProtectedGeo.city_name == city))).scalars().all()
        assert len(prot) == 1 and prot[0].protected_by_agency_id == aid


@pytest.mark.asyncio
async def test_create_geo_blocked(monkeypatch):
    from app.database import async_session, run_migrations
    from app.exceptions import AppException
    from app.models.agency import Agency
    from app.models.protected_geo import ProtectedGeo
    from app.routers.geo import CreateGeoRequest, create_geo_location

    _noop_delay(monkeypatch)
    await run_migrations()
    city = f"Занятый-{uuid.uuid4().hex[:8]}"
    async with async_session() as s:
        agency = Agency(name="Owner", base_city="Геленджик")
        s.add(agency)
        await s.flush()
        s.add(ProtectedGeo(city_name=city, region="КК", status="active", is_active=True))
        await s.commit()
        await s.refresh(agency)
        aid = agency.id

    async with async_session() as s:
        with pytest.raises(AppException) as exc:
            await create_geo_location(aid, CreateGeoRequest(city_name=city, region="КК"), session=s)
    assert exc.value.status_code == 409
    assert exc.value.code == "GEO_PROTECTED"


@pytest.mark.asyncio
async def test_create_geo_partner_offer(monkeypatch):
    from app.database import async_session, run_migrations
    from app.models.agency import Agency
    from app.models.partner_agency import PartnerAgency
    from app.models.protected_geo import ProtectedGeo
    from app.routers.geo import CreateGeoRequest, create_geo_location

    _noop_delay(monkeypatch)
    await run_migrations()
    city = f"Партнёрский-{uuid.uuid4().hex[:8]}"
    async with async_session() as s:
        agency = Agency(name="Owner", base_city="Геленджик")
        s.add(agency)
        await s.flush()
        partner = PartnerAgency(agency_id=agency.id, partner_name="Партнёр", partner_city=city,
                                commission_percent=25.0, is_active=True)
        s.add(partner)
        await s.flush()
        s.add(ProtectedGeo(city_name=city, region="КК", status="active", partner_agency_id=partner.id))
        await s.commit()
        await s.refresh(agency)
        aid = agency.id

    async with async_session() as s:
        resp = await create_geo_location(aid, CreateGeoRequest(city_name=city, region="КК"), session=s)
    # JSONResponse with 202
    assert resp.status_code == 202
