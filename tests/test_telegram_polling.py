"""The `bot` compose service: Telegram long polling (app/services/telegram_polling.py)."""
import asyncio

import pytest

from app.services import telegram_polling as tp


class _Resp:
    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


class _FakeTelegram:
    """Answers deleteWebhook and a scripted sequence of getUpdates."""

    def __init__(self, batches, fail_first=0):
        self.batches = list(batches)
        self.fail_first = fail_first
        self.calls = []

    async def post(self, url, json=None, timeout=None):
        method = url.rsplit("/", 1)[-1]
        self.calls.append((method, dict(json or {})))
        if self.fail_first:
            self.fail_first -= 1
            raise ConnectionError(f"proxy down {url}")
        if method == "deleteWebhook":
            return _Resp({"ok": True, "result": True})
        return _Resp({"ok": True, "result": self.batches.pop(0) if self.batches else []})


def _update(uid, text="/start"):
    return {"update_id": uid, "message": {"chat": {"id": 42}, "text": text}}


@pytest.mark.asyncio
async def test_updates_reach_the_webhook_handler_and_the_offset_moves(monkeypatch):
    seen = []

    async def handler(message, agency_id=None):
        seen.append(message["text"])

    monkeypatch.setattr("app.routers.webhooks.handle_telegram_message", handler)
    fake = _FakeTelegram([[_update(10), _update(11, "/help")], []])
    poller = tp.TelegramPoller("123:ABC", http=fake)

    assert await poller.poll_once() == 2
    assert seen == ["/start", "/help"] and poller.offset == 12
    await poller.poll_once()
    assert fake.calls[-1] == ("getUpdates", {"timeout": tp.POLL_TIMEOUT,
                                             "allowed_updates": tp.ALLOWED_UPDATES,
                                             "offset": 12})


@pytest.mark.asyncio
async def test_a_broken_update_is_skipped_not_fetched_forever(monkeypatch):
    async def handler(message, agency_id=None):
        raise ValueError("boom")

    monkeypatch.setattr("app.routers.webhooks.handle_telegram_message", handler)
    poller = tp.TelegramPoller("123:ABC", http=_FakeTelegram([[_update(5)]]))
    await poller.poll_once()
    assert poller.offset == 6


@pytest.mark.asyncio
async def test_run_drops_the_webhook_first_and_survives_a_dead_proxy(monkeypatch):
    async def handler(message, agency_id=None):
        stop.set()

    async def no_sleep(_):
        return None

    stop = asyncio.Event()
    monkeypatch.setattr("app.routers.webhooks.handle_telegram_message", handler)
    monkeypatch.setattr(tp.asyncio, "sleep", no_sleep)
    fake = _FakeTelegram([[_update(1)]], fail_first=2)
    await asyncio.wait_for(tp.TelegramPoller("123:ABC", http=fake).run(stop), timeout=5)

    methods = [m for m, _ in fake.calls]
    assert methods[:3] == ["deleteWebhook", "deleteWebhook", "deleteWebhook"]
    assert methods[3] == "getUpdates"


@pytest.mark.asyncio
async def test_the_bot_token_never_reaches_the_log(monkeypatch):
    logged = []
    monkeypatch.setattr(tp.logger, "warning", lambda event, **kw: logged.append(kw))
    monkeypatch.setattr(tp.asyncio, "sleep", lambda _: _stop_after_one(stop))
    stop = asyncio.Event()
    fake = _FakeTelegram([], fail_first=1)
    await asyncio.wait_for(tp.TelegramPoller("777:SECRETTOKEN", http=fake).run(stop), timeout=5)
    assert logged and "SECRETTOKEN" not in str(logged)


async def _stop_after_one(stop):
    stop.set()


def test_the_compose_service_points_at_this_module():
    from pathlib import Path

    compose = (Path(__file__).resolve().parent.parent / "docker-compose.yml").read_text(encoding="utf-8")
    assert "python -m app.services.telegram_polling" in compose
