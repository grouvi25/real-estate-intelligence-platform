"""ТЗ «Сигналы» v1.0, апгрейд C: демонстрационный режим."""
import json
import os
import re

import pytest

from app.services.demo import generator

db_only = pytest.mark.skipif(os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL")
OPERATOR_ID = 7_000_000_001


class _Redis:
    def __init__(self, server):
        import fakeredis.aioredis

        self._r = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)

    def __getattr__(self, name):
        return getattr(self._r, name)

    async def aclose(self):
        pass


@pytest.fixture
def demo_redis(monkeypatch):
    import fakeredis

    from app.services.demo import session as demo

    server = fakeredis.FakeServer()
    monkeypatch.setattr(demo, "redis_client", lambda: _Redis(server))
    return server


async def _enable(server, **over):
    from app.services.demo import session as demo

    cfg = {**demo.DEFAULT_CONFIG, "enabled": True, **over}
    r = _Redis(server)
    await demo.cache_config(r, cfg)
    return cfg


async def _session(client, city=None):
    res = await client.post("/api/demo/session", json={"city": city} if city else {})
    assert res.status_code == 201, res.text
    return res.json()


# ---------------------------------------------------------------- data

def test_demo_data_has_no_real_contacts():
    for city in generator.DEMO_CITIES:
        data = generator.build(city)
        assert len(data["signals"]) == 50 and len(data["leads"]) == 20
        blob = json.dumps(data, ensure_ascii=False)
        phones = re.findall(r"\+7[\d\s-]{10,}", blob)
        assert phones and all(p.startswith("+7 900 000-") for p in phones)
        assert "t.me/" not in blob and "vk.com/" not in blob  # no links to real chats
        assert all(s["signal_url"] is None for s in data["signals"])
        assert all(x["is_demo"] and x["demo_label"] for x in data["signals"] + data["leads"])
    assert generator.build("Сочи") == generator.build("Сочи")  # same agency on every refresh
    assert generator.build("Сочи")["signals"][0]["raw_text"] != generator.build("Анапа")["signals"][0]["raw_text"]


def test_activity_looks_live_without_writing():
    from datetime import datetime, timedelta, timezone

    data = generator.build("Анапа")
    t0 = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
    first = generator.respond(data, "/api/signals", {}, "Анапа", now=t0)["signals"][0]["id"]
    later = generator.respond(data, "/api/signals", {}, "Анапа", now=t0 + timedelta(minutes=5))
    assert later["signals"][0]["id"] != first  # another one is «только что»


# ---------------------------------------------------------------- middleware

@pytest.mark.asyncio
async def test_demo_middleware_blocks_settings(client, demo_redis):
    await _enable(demo_redis)
    token = (await _session(client))["token"]
    h = {"X-Demo-Token": token}
    for method, path in [("GET", "/api/admin/managers"), ("GET", "/api/topnlab/settings"),
                         ("GET", "/api/discovery/config"), ("POST", "/api/discovery/run"),
                         ("GET", "/api/properties"), ("POST", "/api/signals/x/create-lead"),
                         ("PATCH", "/api/agency/signal-filter"), ("GET", "/api/leads/export")]:
        res = await client.request(method, path, headers=h, json={})
        assert res.status_code == 403, (method, path, res.status_code)
        assert res.json()["error"] == "demo_restricted"


@pytest.mark.asyncio
async def test_demo_returns_synthetic_signals(client, demo_redis):
    await _enable(demo_redis)
    s = await _session(client, "Геленджик")
    h = {"X-Demo-Token": s["token"]}
    res = await client.get("/api/signals?limit=50", headers=h)
    body = res.json()
    assert res.status_code == 200 and body["count"] == 50
    assert all(x["is_demo"] for x in body["signals"])
    assert any("Геленджике" in x["raw_text"] for x in body["signals"])
    only = (await client.get("/api/signals?category=news", headers=h)).json()
    assert only["count"] and {x["signal_category"] for x in only["signals"]} == {"news"}
    one = body["signals"][0]["id"]
    assert (await client.get(f"/api/signals/{one}", headers=h)).json()["is_demo"]
    lead = (await client.get("/api/leads", headers=h)).json()["leads"][0]
    detail = (await client.get(f"/api/leads/{lead['id']}", headers=h)).json()
    assert detail["is_demo"] and detail["matches"]


@pytest.mark.asyncio
async def test_demo_city_switch(client, demo_redis):
    await _enable(demo_redis)
    h = {"X-Demo-Token": (await _session(client, "Сочи"))["token"]}
    before = (await client.get("/api/signals?limit=5", headers=h)).json()["signals"]
    res = await client.patch("/api/demo/session", headers=h, json={"city": "Анапа"})
    assert res.status_code == 200 and res.json()["city"] == "Анапа"
    after = (await client.get("/api/signals?limit=5", headers=h)).json()["signals"]
    assert {x["id"] for x in before}.isdisjoint({x["id"] for x in after})
    old_signal = before[0]["id"]
    gone = await client.get(f"/api/signals/{old_signal}", headers=h)  # a card of the old city
    assert gone.status_code == 404 and gone.json()["code"] == "NOT_FOUND"
    cfg = (await client.get("/api/auth/config", headers=h)).json()
    assert cfg["agency"]["city"] == "Анапа" and cfg["manager"]["role"] == "demo"
    assert (await client.patch("/api/demo/session", headers=h, json={"city": "Лондон"})).status_code == 400


@pytest.mark.asyncio
async def test_demo_session_expires_and_disabled_demo_opens_nothing(client, demo_redis):
    from app.services.demo import session as demo

    await _enable(demo_redis, session_ttl_min=5)
    s = await _session(client)
    await _Redis(demo_redis).delete(demo.SESSION_KEY.format(s["token"]))  # TTL ran out
    res = await client.get("/api/signals", headers={"X-Demo-Token": s["token"]})
    assert res.status_code == 401 and res.json()["error"] == "demo_expired"
    await _enable(demo_redis, enabled=False)
    assert (await client.post("/api/demo/session", json={})).status_code == 403
    assert (await client.get("/api/demo/config")).json()["enabled"] is False


@pytest.mark.asyncio
async def test_demo_allowed_tabs_are_enforced(client, demo_redis):
    await _enable(demo_redis, allowed_tabs=["dashboard", "signals"])
    h = {"X-Demo-Token": (await _session(client))["token"]}
    assert (await client.get("/api/signals", headers=h)).status_code == 200
    assert (await client.get("/api/analytics/overview", headers=h)).status_code == 200  # dashboard
    assert (await client.get("/api/leads", headers=h)).status_code == 403
    assert (await client.get("/api/analytics/funnel", headers=h)).status_code == 403


@pytest.mark.asyncio
async def test_demo_no_db_queries(client, demo_redis, monkeypatch):
    """Demo answers come from Redis only: opening a session and walking every demo
    screen must not open a single database session."""
    import app.database as database

    await _enable(demo_redis)

    def no_db(*a, **k):
        raise AssertionError("a demo request touched the database")

    monkeypatch.setattr(database, "async_session", no_db)
    monkeypatch.setattr("app.services.demo.session.load_config_from_db", no_db)
    s = await _session(client)
    h = {"X-Demo-Token": s["token"]}
    for path in ["/api/signals", "/api/signals/queue", "/api/leads", "/api/analytics/overview",
                 "/api/analytics/funnel", "/api/analytics/managers", "/api/analytics/timeline",
                 "/api/analytics/source-roi", "/api/analytics/matching-weights", "/api/tasks/summary",
                 "/api/agency/signal-filter", "/api/auth/config"]:
        assert (await client.get(path, headers=h)).status_code == 200, path


@pytest.mark.asyncio
async def test_demo_no_real_data_leak(client, demo_redis):
    """Every GET endpoint of the API, asked with a demo token, either answers with
    demo data or refuses -- none reaches a real handler."""
    from app.main import app

    await _enable(demo_redis)
    h = {"X-Demo-Token": (await _session(client))["token"]}
    paths = {re.sub(r"\{[^}]+\}", "00000000-0000-0000-0000-000000000000", p)
             for p, ops in app.openapi()["paths"].items() if "get" in ops and p.startswith("/api/")}
    paths -= {"/api/demo/config"}  # public, no data
    for path in sorted(paths):
        res = await client.get(path, headers=h)
        assert res.status_code in (200, 403, 404), (path, res.status_code)
        assert res.headers.get("x-demo") == "1", path
        if res.status_code == 200:
            assert "is_demo" in res.text or path == "/api/demo/session", path


# ---------------------------------------------------------------- operator

@db_only
@pytest.mark.asyncio
async def test_demo_toggle(client, demo_redis, monkeypatch):
    from app.config import config
    from app.database import engine, run_migrations
    from app.dependencies import create_operator_token

    monkeypatch.setattr(config, "platform_operator_ids_raw", str(OPERATOR_ID))
    await run_migrations()
    try:
        op = {"Authorization": f"Bearer {create_operator_token(OPERATOR_ID)}"}
        res = await client.patch("/api/demo/settings", headers=op,
                                 json={"enabled": True, "demo_city": "Сочи", "session_ttl_min": 15})
        assert res.status_code == 200 and res.json()["enabled"] is True
        s = await _session(client)
        assert s["city"] == "Сочи" and s["session_ttl_min"] == 15
        assert (await client.patch("/api/demo/settings", headers=op,
                                   json={"demo_city": "Лондон"})).status_code == 400
        assert (await client.patch("/api/demo/settings", json={"enabled": False})).status_code == 401
        res = await client.patch("/api/demo/settings", headers=op, json={"enabled": False})
        assert res.json()["enabled"] is False
        assert (await client.post("/api/demo/session", json={})).status_code == 403
    finally:
        await engine.dispose()


@db_only
@pytest.mark.asyncio
async def test_operator_switches_demo_from_the_sales_bot(demo_redis, monkeypatch):
    from app.database import async_session, engine, run_migrations
    from app.services import sales_bot

    await run_migrations()
    try:
        async with async_session() as s:
            on = await sales_bot._cmd_demo(s, OPERATOR_ID, "on", [])
            status = await sales_bot._cmd_demo(s, OPERATOR_ID, "", [])
            off = await sales_bot._cmd_demo(s, OPERATOR_ID, "off", [])
    finally:
        await engine.dispose()
    assert "включён" in on and "/mini-app/?demo=1" in on
    assert "включён" in status
    assert "выключен" in off


@db_only
@pytest.mark.asyncio
async def test_demo_request_form_reaches_the_operators(client, demo_redis, monkeypatch):
    """«Оставьте заявку»: an onboarding request without Telegram; the operators are
    told to call, and /approve tells them what to say."""
    import uuid

    from app.database import async_session, engine, run_migrations
    from app.models.billing import OnboardingRequest
    from app.services import sales_bot

    told = []

    async def notify(text):
        told.append(text)

    sent = []

    async def send(chat_id, text, reply_markup=None, **kw):
        sent.append(chat_id)
        return True

    monkeypatch.setattr(sales_bot, "notify_operators", notify)
    monkeypatch.setattr(sales_bot, "send", send)
    await run_migrations()
    await _enable(demo_redis)
    h = {"X-Demo-Token": (await _session(client))["token"]}
    city = f"Демоград{uuid.uuid4().hex[:5]}"
    try:
        bad = await client.post("/api/demo/request", headers=h,
                                json={"city": city, "agency_name": "Дом", "phone": "123", "consent": True})
        assert bad.status_code == 400
        no_consent = await client.post("/api/demo/request", headers=h,
                                       json={"city": city, "agency_name": "Дом", "phone": "+7 900 123-45-67"})
        assert no_consent.status_code == 400
        res = await client.post("/api/demo/request", headers=h, json={
            "city": city, "agency_name": "Дом у моря", "name": "Вика",
            "phone": "8 (900) 123-45-67", "consent": True})
        assert res.status_code == 201, res.text
        async with async_session() as s:
            from sqlalchemy import select

            row = (await s.execute(select(OnboardingRequest).where(
                OnboardingRequest.city_name == res.json()["city"]))).scalars().one()
            assert (row.telegram_id, row.source, row.phone) == (None, "demo", "79001234567")
            reply = await sales_bot._cmd_reject(s, OPERATOR_ID, str(row.id)[:8], [])
    finally:
        await engine.dispose()
    assert "из демо" in told[0] and "+79001234567" in told[0]
    assert "позвоните +79001234567" in reply and sent == []  # nobody to message in Telegram
