"""Telegram /start handling and deeplink attribution. TZ 31, 32.6, 35.7, 35.12.

The webhook logged updates and dropped them, so a manager who opened the bot and
typed /start got silence -- the Mini App could only be reached via a link sent by
hand. And a lead qualified from a signal had no way to carry the campaign the
session was opened with.
"""
import pytest

from app.routers.webhooks import (
    UNKNOWN_TEXT,
    WELCOME_TEXT,
    handle_telegram_message,
    mini_app_url,
    start_payload,
)


class _Recorder:
    """Stands in for the bot layer and captures what would be sent."""

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


def test_start_payload_parsing():
    assert start_payload("/start") is None
    assert start_payload("/start vk_promo") == "vk_promo"
    assert start_payload("/start@reip_bot vk_promo") == "vk_promo"
    assert start_payload("/start   ") is None
    assert start_payload("/help") is None
    assert start_payload("") is None


def test_mini_app_url_carries_the_campaign():
    plain = mini_app_url()
    assert plain.endswith("/mini-app/")
    assert "utm_" not in plain

    tagged = mini_app_url("summer sale")
    assert "utm_source=telegram_bot" in tagged
    assert "utm_medium=bot_deeplink" in tagged
    # The payload is URL-encoded, so a space cannot break the query string.
    assert "utm_campaign=summer%20sale" in tagged


@pytest.mark.asyncio
async def test_start_replies_with_a_mini_app_button(bot):
    handled = await handle_telegram_message({"chat": {"id": 42}, "text": "/start"})

    assert handled == "/start"
    assert len(bot.sent) == 1
    chat_id, _platform, message = bot.sent[0]
    assert chat_id == 42
    assert message.text == WELCOME_TEXT
    # web_app buttons are what actually opens the Mini App inside Telegram.
    assert message.buttons[0].mini_app_url.endswith("/mini-app/")


@pytest.mark.asyncio
async def test_start_with_a_deeplink_payload_tags_the_button(bot):
    await handle_telegram_message({"chat": {"id": 7}, "text": "/start vk_promo"})

    url = bot.sent[0][2].buttons[0].mini_app_url
    assert "utm_campaign=vk_promo" in url


@pytest.mark.asyncio
async def test_unknown_command_gets_a_hint_and_plain_text_is_ignored(bot):
    assert await handle_telegram_message({"chat": {"id": 1}, "text": "/wat"}) == "/wat"
    assert bot.sent[-1][2].text == UNKNOWN_TEXT

    before = len(bot.sent)
    assert await handle_telegram_message({"chat": {"id": 1}, "text": "привет"}) is None
    assert await handle_telegram_message({"text": "/start"}) is None  # no chat id
    assert await handle_telegram_message({}) is None
    assert len(bot.sent) == before


def test_mini_app_button_renders_as_web_app():
    """mini_app_url was in the model but never rendered, so the button that opens
    the Mini App could not be sent at all."""
    from app.services.bot_abstraction import BotButton, _telegram_button

    web = _telegram_button(BotButton(text="Открыть", mini_app_url="https://x/mini-app/"))
    assert web == {"text": "Открыть", "web_app": {"url": "https://x/mini-app/"}}

    link = _telegram_button(BotButton(text="Сайт", url="https://x"))
    assert link == {"text": "Сайт", "url": "https://x"}

    cb = _telegram_button(BotButton(text="Да", callback_data="yes"))
    assert cb == {"text": "Да", "callback_data": "yes"}


# --- Bot token must never reach the logs -------------------------------------

def test_send_failure_does_not_log_the_bot_token():
    """httpx puts the failing URL in the exception text, and the Telegram token
    lives in that URL -- so every failed send used to write it out verbatim.
    Seen in production while testing /start."""
    from app.config import config
    from app.services.bot_abstraction import _redact

    err = (
        "Client error '400 Bad Request' for url "
        f"'https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage'"
    )
    safe = _redact(err)

    assert config.telegram_bot_token not in safe
    assert "https://api.telegram.org/bot***" in safe
    # Still useful for debugging.
    assert "400 Bad Request" in safe


def test_redact_handles_text_without_secrets():
    from app.services.bot_abstraction import _redact

    assert _redact("connection timed out") == "connection timed out"
    assert _redact("") == ""
