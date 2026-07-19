"""Tests for the Bot Abstraction Layer (Telegram + MAX) with mocked HTTP."""
import json

import httpx
import pytest

from app.services.bot_abstraction import (
    BotAbstractionLayer,
    BotButton,
    BotMessage,
    BotPlatform,
)


def _layer(handler):
    layer = BotAbstractionLayer()
    layer.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return layer


@pytest.mark.asyncio
async def test_send_telegram_ok_with_buttons():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    layer = _layer(handler)
    msg = BotMessage(text="Привет", buttons=[BotButton(text="Открыть", url="https://example.com")])
    ok = await layer.send_message(12345, BotPlatform.TELEGRAM, msg)
    await layer.close()

    assert ok is True
    assert "/sendMessage" in captured["url"]
    assert captured["body"]["chat_id"] == 12345
    assert captured["body"]["parse_mode"] == "HTML"
    btn = captured["body"]["reply_markup"]["inline_keyboard"][0][0]
    assert btn["text"] == "Открыть"
    assert btn["url"] == "https://example.com"
    assert "callback_data" not in btn  # None values are dropped


@pytest.mark.asyncio
async def test_send_telegram_http_error_returns_false():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"ok": False, "description": "bad"})

    layer = _layer(handler)
    ok = await layer.send_message(1, BotPlatform.TELEGRAM, BotMessage(text="x"))
    await layer.close()
    assert ok is False


@pytest.mark.asyncio
async def test_send_max_ok():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={})

    layer = _layer(handler)
    ok = await layer.send_message(999, BotPlatform.MAX, BotMessage(text="hi"))
    await layer.close()

    assert ok is True
    assert captured["url"].endswith("/messages")
    assert captured["auth"].startswith("Bearer")
