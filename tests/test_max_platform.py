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
