"""Telegram collector tests (TZ 15 + Signal Bus).

No Telethon creds in the test env, so the collector must degrade to safe no-ops.
The username parsing helper is pure.
"""
from types import SimpleNamespace

import pytest

from app.collectors.telegram_collector import TelegramCollector


def test_collector_unavailable_without_creds():
    c = TelegramCollector()
    assert c.is_available() is False


def test_username_parsing():
    assert TelegramCollector._username(SimpleNamespace(external_id="@foo", source_url=None)) == "foo"
    assert TelegramCollector._username(
        SimpleNamespace(external_id=None, source_url="https://t.me/bar")) == "bar"
    assert TelegramCollector._username(
        SimpleNamespace(external_id=None, source_url="https://example.com")) is None


@pytest.mark.asyncio
async def test_search_sources_noop_without_creds():
    c = TelegramCollector()
    assert await c.search_sources(["Геленджик купить"]) == []


@pytest.mark.asyncio
async def test_collect_from_source_noop_without_creds():
    c = TelegramCollector()
    # Returns before touching the session/source when unavailable.
    assert await c.collect_from_source(None, None, {}, limit=10) == 0


@pytest.mark.asyncio
async def test_collect_task_noop_without_creds():
    from worker.tasks.collector_tasks import _collect_telegram_sources

    assert await _collect_telegram_sources() == 0


@pytest.mark.asyncio
async def test_source_finder_search_empty_without_creds():
    from app.discovery.source_finder import search_telegram_sources

    res = await search_telegram_sources({"search_queries": {"telegram": ["Геленджик"]}})
    assert res == []
