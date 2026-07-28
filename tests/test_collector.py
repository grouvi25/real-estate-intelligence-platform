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


class _FakeSession:
    """Minimal stand-in for a Telethon session (records DC assignments)."""

    def __init__(self):
        self.dc_id = 2
        self.server_address = "149.154.167.51"
        self.calls = []

    def set_dc(self, dc_id, ip, port):
        self.calls.append((dc_id, ip, port))
        self.dc_id, self.server_address = dc_id, ip


class _FakeClient:
    def __init__(self):
        self.session = _FakeSession()


def test_force_dc_port_pins_the_current_dc():
    from app.collectors.telegram_collector import force_dc_port

    client = _FakeClient()
    force_dc_port(client, 5222)

    assert client.session.calls[-1] == (2, "149.154.167.51", 5222)


def test_force_dc_port_survives_a_dc_migration():
    """Telethon re-reads DC options from the server on migration, and those
    always name 443 -- the port must stay pinned across that."""
    from app.collectors.telegram_collector import force_dc_port

    client = _FakeClient()
    force_dc_port(client, 5222)
    client.session.set_dc(4, "149.154.167.91", 443)  # as the server would

    assert client.session.calls[-1] == (4, "149.154.167.91", 5222)
    assert all(port == 5222 for _, _, port in client.session.calls)


def test_username_parsing():
    assert TelegramCollector._username(SimpleNamespace(external_id="@foo", source_url=None)) == "foo"
    assert TelegramCollector._username(
        SimpleNamespace(external_id=None, source_url="https://t.me/bar")) == "bar"
    assert TelegramCollector._username(
        SimpleNamespace(external_id=None, source_url="https://example.com")) is None


def test_username_prefers_url_over_numeric_external_id():
    """Discovery stores the numeric chat id in external_id and the username in
    source_url; Telethon cannot resolve a bare numeric id, so the URL wins."""
    source = SimpleNamespace(
        external_id="1221707220", source_url="https://t.me/barahoolka_gelendzhik"
    )
    assert TelegramCollector._username(source) == "barahoolka_gelendzhik"


def test_username_numeric_id_without_url():
    assert TelegramCollector._username(
        SimpleNamespace(external_id="1221707220", source_url=None)) == "1221707220"


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
