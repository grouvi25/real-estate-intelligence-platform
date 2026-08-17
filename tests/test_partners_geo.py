"""Partners + geo management endpoint tests (need PostgreSQL)."""
import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL"
)


async def _agency(s):
    from app.models.agency import Agency

    a = Agency(name="PG Agency", base_city="Геленджик")
    s.add(a)
    await s.flush()
    return a


async def _owner(s, agency):
    """Владелец агентства настоящей строкой в базе.

    Создание гео и партнёров защищено require_owner: она читает менеджера по
    его id. Строковый "m1" даже не разбирался как uuid — тест падал на
    ValueError раньше, чем доходил до проверки прав.
    """
    from app.dependencies import CurrentManager
    from app.models.manager import Manager

    manager = Manager(agency_id=agency.id, name="Владелец", role="owner")
    s.add(manager)
    await s.commit()
    return CurrentManager(manager_id=str(manager.id), agency_id=str(agency.id))


@pytest.mark.asyncio
async def test_partner_create_and_list():
    from app.database import async_session, run_migrations
    from app.routers.partners import CreatePartnerRequest, create_partner, list_partners

    await run_migrations()
    async with async_session() as s:
        agency = await _agency(s)
        await s.commit()
        current = await _owner(s, agency)

    async with async_session() as s:
        created = await create_partner(
            CreatePartnerRequest(partner_name="Партнёр Сочи", partner_city="Сочи",
                                 contact_telegram="123456", commission_percent=30.0),
            current=current, session=s)
        assert created["partner_name"] == "Партнёр Сочи"
        assert created["is_active"] is True

    async with async_session() as s:
        listed = await list_partners(current=current, session=s)
        assert listed["count"] >= 1
        assert any(p["partner_city"] == "Сочи" for p in listed["partners"])


@pytest.mark.asyncio
async def test_geo_create_and_list(monkeypatch):
    from app.database import async_session, run_migrations
    from app.routers.geo import CreateGeoRequest, create_geo, list_geo

    import worker.tasks.geo_tasks as gt
    monkeypatch.setattr(gt.generate_keywords_for_geo, "delay", lambda *a, **k: None)

    await run_migrations()
    async with async_session() as s:
        agency = await _agency(s)
        await s.commit()
        current = await _owner(s, agency)

    # A fixed name made the test pass once and fail for ever after: creating the
    # city reserves it in protected_geos, so the second run got 409 GEO_PROTECTED
    # from its own leftovers.
    city = f"Владивосток-{uuid.uuid4().hex[:8]}"

    async with async_session() as s:
        res = await create_geo(
            CreateGeoRequest(city_name=city, region="Приморский край"),
            current=current, session=s)
        # dict (allowed) — not a partner_offer JSONResponse
        assert isinstance(res, dict) and res.get("geo_protected") is True

    async with async_session() as s:
        listed = await list_geo(current=current, session=s)
        assert listed["count"] >= 1
        assert any(g["city_name"] == city for g in listed["geo"])
