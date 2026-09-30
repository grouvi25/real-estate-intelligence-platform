"""ТЗ «SaaS-слой» v1, разделы 2-3: subscription gate and plan limits."""
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.exceptions import AppException
from app.services import billing

db_only = pytest.mark.skipif(os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL")
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def _agency(active=True, expires=None, **kw):
    return SimpleNamespace(subscription_active=active, subscription_expires_at=expires,
                           subscription_plan="start", max_managers=kw.get("max_managers"),
                           max_cities=kw.get("max_cities"))


@pytest.mark.parametrize("agency,status", [
    (_agency(expires=None), "active"),                       # lifetime: agencies before billing
    (_agency(expires=NOW + timedelta(days=1)), "active"),
    (_agency(expires=NOW - timedelta(days=3)), "grace"),
    (_agency(expires=NOW - timedelta(days=15)), "expired"),
    (_agency(active=False, expires=None), "expired"),        # suspended by the operator
])
def test_status(agency, status):
    assert billing.get_subscription_status(agency, NOW) == status


def test_grace_reads_but_does_not_write():
    agency = _agency(expires=NOW - timedelta(days=3))
    billing.gate_request(agency, "GET", "/api/leads", now=NOW)
    with pytest.raises(AppException) as err:
        billing.gate_request(agency, "POST", "/api/leads", now=NOW)
    assert (err.value.status_code, err.value.code) == (402, "SUBSCRIPTION_GRACE")
    assert "12.10.2026" in err.value.detail  # 28.09 expiry + 14 days, so the owner knows


def test_expired_is_blocked_except_what_explains_it():
    agency = _agency(expires=NOW - timedelta(days=30))
    for method, path in (("GET", "/api/leads"), ("POST", "/api/signals/x/create-lead")):
        with pytest.raises(AppException) as err:
            billing.gate_request(agency, method, path, now=NOW)
        assert (err.value.status_code, err.value.code) == (402, "SUBSCRIPTION_EXPIRED")
    billing.gate_request(agency, "GET", "/api/billing/status", now=NOW)
    billing.gate_request(agency, "GET", "/api/auth/config", now=NOW)


def test_plan_limits_null_means_unlimited():
    billing.check_plan_limit(_agency(), "managers", 500)
    billing.check_plan_limit(_agency(max_managers=3), "managers", 2)
    with pytest.raises(AppException) as err:
        billing.check_plan_limit(_agency(max_managers=3), "managers", 3)
    assert (err.value.status_code, err.value.code) == (403, "PLAN_LIMIT_MANAGERS")
    with pytest.raises(AppException) as err:
        billing.check_plan_limit(_agency(max_cities=1), "cities", 1)
    assert err.value.code == "PLAN_LIMIT_CITIES"


# --------------------------------------------------------------- live database

async def _seed(**agency_kw):
    from tests.helpers import unique_telegram_id

    from app.database import async_session, run_migrations
    from app.models.agency import Agency
    from app.models.manager import Manager

    await run_migrations()
    async with async_session() as s:
        agency = Agency(name="SaaS", base_city="Анапа", invite_token=os.urandom(8).hex(), **agency_kw)
        s.add(agency)
        await s.flush()
        owner = Manager(agency_id=agency.id, name="Владелец", role="owner",
                        telegram_id=unique_telegram_id(), is_active=True)
        s.add(owner)
        await s.commit()
        return agency.id, owner.id, agency.invite_token


def _client_for(owner_id, agency_id):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.security import create_access_token

    token = create_access_token(str(owner_id), agency_id=str(agency_id))
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@db_only
@pytest.mark.asyncio
async def test_http_gate_for_an_expired_agency():
    from app.database import engine

    try:
        agency_id, owner_id, _ = await _seed(subscription_expires_at=datetime.now(timezone.utc) - timedelta(days=40))
    finally:
        await engine.dispose()
    client = _client_for(owner_id, agency_id)
    blocked = client.get("/api/leads")
    assert blocked.status_code == 402 and blocked.json()["code"] == "SUBSCRIPTION_EXPIRED"
    status = client.get("/api/billing/status")
    assert status.status_code == 200 and status.json()["status"] == "expired"
    assert status.json()["usage"] == {"managers": 1, "cities": 0}


@db_only
@pytest.mark.asyncio
async def test_http_gate_in_grace_and_for_a_lifetime_agency():
    from app.database import engine

    try:
        grace_id, grace_owner, _ = await _seed(subscription_expires_at=datetime.now(timezone.utc) - timedelta(days=2))
        life_id, life_owner, _ = await _seed()
    finally:
        await engine.dispose()
    grace = _client_for(grace_owner, grace_id)
    assert grace.get("/api/leads").status_code == 200
    assert grace.post("/api/leads", json={}).status_code == 402
    assert _client_for(life_owner, life_id).get("/api/billing/status").json()["status"] == "active"


@db_only
@pytest.mark.asyncio
async def test_invite_beyond_the_plan_is_refused(monkeypatch):
    from tests.helpers import unique_telegram_id
    from tests.test_auth import build_tg_init_data

    from app.config import config
    from app.database import async_session, engine
    from app.routers.auth import AuthRequest, auth_platform

    monkeypatch.setattr(config, "telegram_bot_token", "tg-test-token")
    try:
        agency_id, _, invite = await _seed(max_managers=2)
        joined = []
        for _ in range(2):
            init = build_tg_init_data("tg-test-token", {"id": unique_telegram_id(), "first_name": "М"})
            async with async_session() as s:
                try:
                    joined.append(await auth_platform(
                        AuthRequest(platform="telegram", init_data=init, invite=invite), session=s))
                except AppException as e:
                    joined.append(e)
    finally:
        await engine.dispose()
    assert "token" in joined[0]  # owner + 1 = 2 seats
    assert isinstance(joined[1], AppException) and joined[1].code == "PLAN_LIMIT_MANAGERS"


@db_only
@pytest.mark.asyncio
async def test_second_city_on_a_one_city_plan_is_refused(monkeypatch):
    from app.database import async_session, engine
    from app.dependencies import CurrentManager
    from app.models.geo_location import GeoLocation
    from app.routers.geo import CreateGeoRequest, create_geo

    try:
        agency_id, owner_id, _ = await _seed(max_cities=1)
        async with async_session() as s:
            s.add(GeoLocation(agency_id=agency_id, city_name="Анапа", geo_type="base"))
            await s.commit()
        async with async_session() as s:
            with pytest.raises(AppException) as err:
                await create_geo(CreateGeoRequest(city_name="Сочи-" + os.urandom(3).hex(), region="КК"),
                                 current=CurrentManager(str(owner_id), str(agency_id)), session=s)
    finally:
        await engine.dispose()
    assert err.value.code == "PLAN_LIMIT_CITIES"


@db_only
@pytest.mark.asyncio
async def test_collection_skips_agencies_past_grace():
    from sqlalchemy import select

    from app.database import async_session, engine
    from app.models.agency import Agency

    try:
        paid, _, _ = await _seed(subscription_expires_at=datetime.now(timezone.utc) + timedelta(days=5))
        grace, _, _ = await _seed(subscription_expires_at=datetime.now(timezone.utc) - timedelta(days=5))
        gone, _, _ = await _seed(subscription_expires_at=datetime.now(timezone.utc) - timedelta(days=20))
        off, _, _ = await _seed(subscription_active=False)
        async with async_session() as s:
            ids = set((await s.execute(select(Agency.id).where(
                Agency.id.in_([paid, grace, gone, off]),
                Agency.id.in_(billing.collectable_agency_ids())))).scalars())
    finally:
        await engine.dispose()
    assert ids == {paid, grace}
