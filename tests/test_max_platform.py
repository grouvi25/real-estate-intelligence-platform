"""MAX platform support: initData validation, sending, webhook. TZ 13.1, 31, 35.2.

MAX login was refused outright in production because the signature scheme was
believed to be undocumented. It is documented (dev.max.ru/docs/webapps/validation)
and matches Telegram's construction, with one difference: MAX signs URL-decoded
values. Sending was wrong in three separate ways, so every MAX message would have
failed, and the webhook accepted anything that reached the URL.
"""
import hashlib
import hmac
import json
import os
from urllib.parse import quote

import pytest

from app.config import config
from app.routers.auth import verify_max_init_data

BOT_TOKEN = "max-test-token"


def _sign(params: dict, token: str = BOT_TOKEN) -> str:
    """Build a valid MAX initData string: values URL-encoded, signature over the
    decoded values sorted by key."""
    check = "\n".join(f"{k}={params[k]}" for k in sorted(params))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    encoded = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in params.items())
    return f"{encoded}&hash={digest}"


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    monkeypatch.setattr(config, "max_bot_token", BOT_TOKEN)


def _params(**over):
    import time

    base = {
        "auth_date": str(int(time.time())),
        "query_id": "AAH123",
        "user": json.dumps({"id": 555, "first_name": "Иван"}, ensure_ascii=False),
    }
    base.update(over)
    return base


def test_valid_signature_returns_the_user():
    user = verify_max_init_data(_sign(_params()))
    assert user == {"id": 555, "first_name": "Иван"}


def test_tampered_payload_is_rejected():
    """The whole point: nobody may claim to be another manager."""
    signed = _sign(_params())
    forged = signed.replace(quote(json.dumps({"id": 555, "first_name": "Иван"}, ensure_ascii=False), safe=""),
                            quote(json.dumps({"id": 999, "first_name": "Взломщик"}, ensure_ascii=False), safe=""))
    assert verify_max_init_data(forged) is None


def test_signature_from_a_different_bot_token_is_rejected():
    assert verify_max_init_data(_sign(_params(), token="someone-elses-token")) is None


def test_missing_or_duplicated_hash_is_rejected():
    params = _params()
    unsigned = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in params.items())
    assert verify_max_init_data(unsigned) is None
    assert verify_max_init_data(_sign(params) + "&hash=deadbeef") is None


def test_stale_init_data_is_rejected():
    """Replay protection: a captured login must not work forever."""
    assert verify_max_init_data(_sign(_params(auth_date="1700000000"))) is None


def test_no_bot_token_means_no_login(monkeypatch):
    monkeypatch.setattr(config, "max_bot_token", None)
    assert verify_max_init_data(_sign(_params())) is None


def test_garbage_input_is_rejected():
    for bad in ("", "not-init-data", "hash=", "user=%7Bbroken&hash=x"):
        assert verify_max_init_data(bad) is None


# --- sending ----------------------------------------------------------------

def test_max_button_opens_the_mini_app_by_bot_name(monkeypatch):
    """MAX opens a Mini App by naming the bot, not by URL, so the deeplink
    payload travels in `payload`."""
    from app.services.bot_abstraction import BotButton, _max_button

    monkeypatch.setattr(config, "max_bot_username", "reip_bot")
    btn = _max_button(BotButton(text="Открыть", mini_app_url="https://x/mini-app/?utm_campaign=vk_promo"))
    assert btn == {"type": "open_app", "text": "Открыть", "web_app": "reip_bot", "payload": "vk_promo"}


def test_max_button_falls_back_to_a_link_without_a_bot_username(monkeypatch):
    from app.services.bot_abstraction import BotButton, _max_button

    monkeypatch.setattr(config, "max_bot_username", None)
    btn = _max_button(BotButton(text="Сайт", url="https://x"))
    assert btn == {"type": "link", "text": "Сайт", "url": "https://x"}


@pytest.mark.asyncio
async def test_send_uses_the_max_api_contract(monkeypatch):
    """Three things differed from Telegram and were all wrong: no "Bearer"
    prefix, recipient as a query parameter, buttons as an attachment."""
    from app.services.bot_abstraction import BotButton, BotMessage, BotAbstractionLayer

    monkeypatch.setattr(config, "max_bot_username", "reip_bot")
    layer = BotAbstractionLayer()
    seen = {}

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            return None

    async def fake_post(url, params=None, headers=None, json=None):
        seen.update(url=url, params=params, headers=headers, body=json)
        return _Resp()

    monkeypatch.setattr(layer.http, "post", fake_post)
    ok = await layer._send_max(555, BotMessage(
        text="Привет", buttons=[BotButton(text="Открыть", mini_app_url="https://x/mini-app/")]))

    assert ok is True
    assert seen["url"].endswith("/messages")
    assert seen["params"] == {"user_id": 555}
    assert seen["headers"]["Authorization"] == BOT_TOKEN  # no "Bearer "
    assert seen["body"]["text"] == "Привет"
    assert seen["body"]["attachments"][0]["type"] == "inline_keyboard"
    assert seen["body"]["attachments"][0]["payload"]["buttons"][0][0]["type"] == "open_app"


# --- webhook ----------------------------------------------------------------

class _Recorder:
    def __init__(self):
        self.sent = []

    async def send_message(self, user_id, platform, message):
        self.sent.append((user_id, platform, message))
        return True


@pytest.fixture
def bot(monkeypatch):
    import app.services.bot_abstraction as ba

    rec = _Recorder()
    monkeypatch.setattr(ba, "bot_layer", rec)
    return rec


@pytest.mark.asyncio
async def test_bot_started_is_treated_as_start(bot):
    from app.routers.webhooks import WELCOME_TEXT, handle_max_event

    handled = await handle_max_event({
        "update_type": "bot_started",
        "message": {"sender": {"user_id": 42}},
    })

    assert handled == "bot_started"
    assert bot.sent[0][0] == 42
    assert bot.sent[0][2].text == WELCOME_TEXT


@pytest.mark.asyncio
async def test_message_created_with_start_and_payload(bot):
    from app.routers.webhooks import handle_max_event

    await handle_max_event({
        "update_type": "message_created",
        "message": {"sender": {"user_id": 7}, "body": {"text": "/start vk_promo"}},
    })

    assert "utm_campaign=vk_promo" in bot.sent[0][2].buttons[0].mini_app_url


@pytest.mark.asyncio
async def test_irrelevant_events_are_ignored(bot):
    from app.routers.webhooks import handle_max_event

    assert await handle_max_event({"update_type": "message_callback"}) is None
    assert await handle_max_event({"update_type": "message_created",
                                   "message": {"body": {"text": "/start"}}}) is None  # no sender
    assert await handle_max_event({"update_type": "message_created",
                                   "message": {"sender": {"user_id": 1},
                                               "body": {"text": "привет"}}}) is None
    assert bot.sent == []


# --- an unconfigured secret must not mean "trust everyone" --------------------

def _post(client, path, headers=None):
    return client.post(path, json={"update_type": "message_created"}, headers=headers or {})


@pytest.mark.parametrize("path,header", [
    ("/api/webhooks/max", "X-Max-Bot-Api-Secret"),
    ("/api/webhooks/telegram", "X-Telegram-Bot-Api-Secret-Token"),
])
def test_webhook_refuses_when_no_secret_is_configured(monkeypatch, path, header):
    """TZ 35.2 asks for 403 on an unsigned webhook. An unset secret used to skip
    the check entirely, so the MAX endpoint answered 200 to anything that reached
    the URL -- confirmed against production."""
    from fastapi.testclient import TestClient

    from app.config import config as app_config
    from app.main import app

    monkeypatch.setattr(app_config, "node_env", "production")
    monkeypatch.setattr(app_config, "max_webhook_secret", None)
    monkeypatch.setattr(app_config, "telegram_webhook_secret", None)

    with TestClient(app) as client:
        assert _post(client, path).status_code == 403
        assert _post(client, path, {header: "guessed"}).status_code == 403


@pytest.mark.parametrize("path,header,attr", [
    ("/api/webhooks/max", "X-Max-Bot-Api-Secret", "max_webhook_secret"),
    ("/api/webhooks/telegram", "X-Telegram-Bot-Api-Secret-Token", "telegram_webhook_secret"),
])
def test_webhook_accepts_the_configured_secret(monkeypatch, path, header, attr):
    from fastapi.testclient import TestClient

    from app.config import config as app_config
    from app.main import app

    monkeypatch.setattr(app_config, "node_env", "production")
    monkeypatch.setattr(app_config, attr, "s3cret")

    with TestClient(app) as client:
        assert _post(client, path, {header: "s3cret"}).status_code == 200
        assert _post(client, path, {header: "wrong"}).status_code == 403


# --- Окно саморегистрации владельцев ---------------------------------------
#
# Механизм выдаёт права владельца агентства без приглашения, поэтому проверяются
# именно его границы: ровно столько мест, сколько выдано, только из MAX и только
# незнакомым. Ошибка здесь стоит чужого доступа ко всему кабинету.

db_only = pytest.mark.skipif(
    os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL")


async def _set_slots(session, n: int) -> None:
    from sqlalchemy import text

    await session.execute(text("UPDATE platform_claim SET remaining = :n"), {"n": n})
    await session.commit()


async def _slots(session) -> int:
    from sqlalchemy import text

    row = (await session.execute(text("SELECT remaining FROM platform_claim"))).first()
    return int(row[0]) if row else -1


async def _owner_agency(session):
    from app.models.agency import Agency

    agency = Agency(name="Claim Agency", base_city="Геленджик")
    session.add(agency)
    await session.commit()
    return agency


def _max_login(user_id: int, name: str = "Гость"):
    from app.routers.auth import AuthRequest

    return AuthRequest(
        platform="max",
        init_data=_sign(_params(user=json.dumps({"id": user_id, "first_name": name},
                                                ensure_ascii=False))),
    )


@db_only
@pytest.mark.asyncio
async def test_the_window_admits_exactly_two_and_then_closes(monkeypatch):
    from app.database import async_session, run_migrations
    from app.exceptions import AppException
    from app.routers.auth import auth_platform

    await run_migrations()
    async with async_session() as s:
        agency = await _owner_agency(s)
        monkeypatch.setattr(config, "platform_owner_agency_id", str(agency.id))
        monkeypatch.setattr(config, "max_admin_ids_raw", "")
        await _set_slots(s, 2)

    async with async_session() as s:
        first = await auth_platform(_max_login(900001, "Первый"), session=s)
        assert first["manager"]["role"] == "owner"
        assert str(first["manager"]["agency_id"]) == str(agency.id)
        assert await _slots(s) == 1

    async with async_session() as s:
        second = await auth_platform(_max_login(900002, "Второй"), session=s)
        assert second["manager"]["role"] == "owner"
        assert await _slots(s) == 0

    # Третий — уже мимо: окно закрылось само, без чьего-либо участия.
    async with async_session() as s:
        with pytest.raises(AppException) as refused:
            await auth_platform(_max_login(900003, "Третий"), session=s)
        assert refused.value.status_code == 403


@db_only
@pytest.mark.asyncio
async def test_the_window_does_not_open_for_telegram(monkeypatch):
    """Свободное место в MAX не должно впускать незнакомца из Telegram."""
    from app.database import async_session, run_migrations
    from app.exceptions import AppException
    from app.routers.auth import AuthRequest, auth_platform
    from tests.test_auth import build_tg_init_data

    await run_migrations()
    async with async_session() as s:
        agency = await _owner_agency(s)
        monkeypatch.setattr(config, "platform_owner_agency_id", str(agency.id))
        monkeypatch.setattr(config, "telegram_bot_token", "tg-test-token")
        monkeypatch.setattr(config, "admin_telegram_id", None)
        await _set_slots(s, 2)

    async with async_session() as s:
        req = AuthRequest(platform="telegram", init_data=build_tg_init_data(
            "tg-test-token", {"id": 900101, "first_name": "Чужой"}))
        with pytest.raises(AppException) as refused:
            await auth_platform(req, session=s)
        assert refused.value.status_code == 403
        assert await _slots(s) == 2  # место не потрачено


@db_only
@pytest.mark.asyncio
async def test_listed_max_admin_gets_in_without_spending_a_slot(monkeypatch):
    from app.database import async_session, run_migrations
    from app.routers.auth import auth_platform

    await run_migrations()
    async with async_session() as s:
        agency = await _owner_agency(s)
        monkeypatch.setattr(config, "platform_owner_agency_id", str(agency.id))
        monkeypatch.setattr(config, "max_admin_ids_raw", "900201, 900202")
        await _set_slots(s, 2)

    async with async_session() as s:
        res = await auth_platform(_max_login(900201, "Доверенный"), session=s)
        assert res["manager"]["role"] == "owner"
        assert await _slots(s) == 2  # известный по списку места не занимает
