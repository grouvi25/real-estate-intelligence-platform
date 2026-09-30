"""ТЗ «SaaS-слой» v1, раздел 4: one bot per agency."""
import asyncio
import os
from types import SimpleNamespace

import pytest

db_only = pytest.mark.skipif(os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL")
AGENCY_TOKEN = "7000000001:AAagencyBotTokenForTestsOnly_xxxxxxxxxx"


class _Resp:
    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body

    def raise_for_status(self):
        return None


class _FakeTelegram:
    def __init__(self, answers=None):
        self.answers = answers or {}
        self.calls = []

    async def post(self, url, json=None, timeout=None):
        token, method = url.split("/bot", 1)[1].split("/", 1)
        self.calls.append((token, method, json))
        return _Resp(self.answers.get(method, {"ok": True, "result": True}))


@pytest.fixture
def telegram(monkeypatch):
    from app.services.bot_abstraction import bot_layer

    fake = _FakeTelegram()
    monkeypatch.setattr(bot_layer, "_telegram_http", fake)
    return fake


# ----------------------------------------------------------------- sending

@pytest.mark.asyncio
async def test_a_message_goes_out_through_the_bot_it_is_given(telegram):
    from app.config import config
    from app.services.bot_abstraction import BotMessage, BotPlatform, bot_layer

    await bot_layer.send_message(1, BotPlatform.TELEGRAM, BotMessage(text="a"))
    await bot_layer.send_message(1, BotPlatform.TELEGRAM, BotMessage(text="b"), AGENCY_TOKEN)
    assert [c[0] for c in telegram.calls] == [config.telegram_bot_token, AGENCY_TOKEN]


def test_agency_bot_tokens_are_scrubbed_from_logs():
    from app.services.bot_abstraction import _redact

    assert AGENCY_TOKEN not in _redact(f"ConnectError for {AGENCY_TOKEN} somewhere")
    assert AGENCY_TOKEN not in _redact(f"https://api.telegram.org/bot{AGENCY_TOKEN}/sendMessage")


def test_brand_only_lets_through_safe_values():
    from app.routers.auth import brand_of

    ok = SimpleNamespace(brand_color="#1a2B3c", logo_url="https://cdn.example/logo.png",
                         telegram_bot_username="GelBot")
    assert brand_of(ok) == {"color": "#1a2B3c", "logo_url": "https://cdn.example/logo.png",
                            "bot_username": "GelBot"}
    bad = SimpleNamespace(brand_color="red;} body{display:none", logo_url="javascript:alert(1)",
                          telegram_bot_username=None)
    assert brand_of(bad) is None


# ----------------------------------------------------------------- polling

@pytest.mark.asyncio
async def test_supervisor_follows_the_agency_bots_in_the_database(monkeypatch):
    from app.services import telegram_polling as tp

    runs = []

    async def fake_run(self, stop=None):
        runs.append((self.agency_id, self.token))
        await asyncio.Event().wait()

    wanted = {"a1": "1:A", "a2": "2:B"}

    async def tokens():
        return dict(wanted)

    monkeypatch.setattr(tp.TelegramPoller, "run", fake_run)
    monkeypatch.setattr(tp, "agency_bot_tokens", tokens)
    sup = tp.PollingSupervisor({"platform": tp.TelegramPoller("0:P")})
    await sup.sync()
    await asyncio.sleep(0)
    assert set(sup.tasks) == {"platform", "agency:a1", "agency:a2"}

    wanted.pop("a1")
    wanted["a2"] = "2:NEW"  # token replaced -> the old poller must stop
    await sup.sync()
    await asyncio.sleep(0)
    assert set(sup.tasks) == {"platform", "agency:a2"}
    assert sup.tasks["agency:a2"][0] == "2:NEW"
    assert ("a2", "2:NEW") in runs
    for _, task in sup.tasks.values():
        task.cancel()


# --------------------------------------------------------------- database

async def _agency_with_bot():
    from tests.helpers import unique_telegram_id

    from app.database import async_session, run_migrations
    from app.models.agency import Agency
    from app.models.manager import Manager

    await run_migrations()
    async with async_session() as s:
        agency = Agency(name="Бот агентства", base_city="Анапа",
                        telegram_webhook_secret="agency-secret-0001",
                        welcome_message="Здравствуйте! Это кабинет «Анапа-Дом».")
        agency.telegram_bot_token = AGENCY_TOKEN + os.urandom(3).hex()
        s.add(agency)
        await s.flush()
        manager = Manager(agency_id=agency.id, name="Ирина", role="manager",
                          telegram_id=unique_telegram_id(), is_active=True,
                          preferred_platform="telegram")
        s.add(manager)
        await s.commit()
        return agency.id, agency.telegram_bot_token, manager.id, manager.telegram_id


@db_only
@pytest.mark.asyncio
async def test_a_manager_hears_from_the_agency_bot(telegram):
    from app.database import engine
    from app.services.bot_abstraction import bot_layer

    try:
        _, token, manager_id, _ = await _agency_with_bot()
        assert await bot_layer.notify_manager(str(manager_id), "новый лид")
    finally:
        await engine.dispose()
    assert telegram.calls[-1][0] == token


@db_only
@pytest.mark.asyncio
async def test_the_cabinet_opens_from_the_agency_bot(monkeypatch):
    from tests.test_auth import build_tg_init_data

    from app.config import config
    from app.database import async_session, engine
    from app.routers.auth import AuthRequest, auth_platform

    monkeypatch.setattr(config, "telegram_bot_token", "platform-token")
    try:
        agency_id, token, _, tg_id = await _agency_with_bot()
        init = build_tg_init_data(token, {"id": tg_id, "first_name": "Ирина"})
        async with async_session() as s:
            res = await auth_platform(AuthRequest(platform="telegram", init_data=init), session=s)
        forged = build_tg_init_data("9:not-a-bot-we-know", {"id": tg_id, "first_name": "Ирина"})
        async with async_session() as s:
            with pytest.raises(Exception) as refused:
                await auth_platform(AuthRequest(platform="telegram", init_data=forged), session=s)
    finally:
        await engine.dispose()
    assert res["manager"]["agency_id"] == str(agency_id)
    assert getattr(refused.value, "status_code", None) == 401


@db_only
@pytest.mark.asyncio
async def test_agency_webhook_needs_its_own_secret(monkeypatch):
    from fastapi.testclient import TestClient

    from app.database import engine
    from app.main import app

    handled = []

    async def handler(message, agency_id=None):
        handled.append((message["text"], agency_id))

    monkeypatch.setattr("app.routers.webhooks.handle_telegram_message", handler)
    try:
        agency_id, _, _, _ = await _agency_with_bot()
    finally:
        await engine.dispose()
    client = TestClient(app)
    update = {"update_id": 1, "message": {"chat": {"id": 5}, "text": "/start"}}
    url = f"/api/webhooks/tg/{agency_id}"
    assert client.post(url, json=update).status_code == 403
    assert client.post(url, json=update, headers={
        "X-Telegram-Bot-Api-Secret-Token": "wrong"}).status_code == 403
    ok = client.post(url, json=update, headers={"X-Telegram-Bot-Api-Secret-Token": "agency-secret-0001"})
    assert ok.status_code == 200 and handled == [("/start", str(agency_id))]
    assert client.post("/api/webhooks/tg/not-a-uuid", json=update).status_code == 403


@db_only
@pytest.mark.asyncio
async def test_start_in_the_agency_bot_answers_with_its_welcome(telegram):
    from app.database import engine
    from app.routers.webhooks import handle_telegram_message

    try:
        agency_id, token, _, _ = await _agency_with_bot()
        await handle_telegram_message({"chat": {"id": 77}, "text": "/start"}, agency_id=str(agency_id))
    finally:
        await engine.dispose()
    sent_token, method, body = telegram.calls[-1]
    assert (sent_token, method) == (token, "sendMessage")
    assert body["text"].startswith("Здравствуйте! Это кабинет «Анапа-Дом».")


@db_only
@pytest.mark.asyncio
async def test_attaching_a_bot_checks_it_and_keeps_it_unique(telegram, monkeypatch):
    from app.config import config
    from app.database import async_session, engine, run_migrations
    from app.models.agency import Agency
    from app.services import agency_bots

    username = "AnapaDom" + os.urandom(3).hex() + "Bot"
    telegram.answers["getMe"] = {"ok": True, "result": {"is_bot": True, "username": username}}
    monkeypatch.setattr(config, "telegram_updates_mode", "webhook")
    token = "7000000002:" + os.urandom(20).hex()
    await run_migrations()
    try:
        async with async_session() as s:
            first = Agency(name="Первое", base_city="Анапа")
            second = Agency(name="Второе", base_city="Сочи")
            s.add_all([first, second])
            await s.commit()
            assert await agency_bots.attach_bot(s, first, token) == username
            assert first.telegram_bot_token == token and first.telegram_webhook_secret
            set_hook = [c for c in telegram.calls if c[1] == "setWebhook"][-1][2]
            assert set_hook["url"].endswith(f"/api/webhooks/tg/{first.id}")
            with pytest.raises(agency_bots.AgencyBotError):
                await agency_bots.attach_bot(s, second, token)
            with pytest.raises(agency_bots.AgencyBotError):
                await agency_bots.attach_bot(s, second, "not a token")
            raw = (await s.execute(__import__("sqlalchemy").text(
                "select telegram_bot_token_encrypted from agencies where id = :i"), {"i": first.id})).scalar()
            assert token.encode() not in bytes(raw)  # stored encrypted
    finally:
        await engine.dispose()
