"""VK collector: discovery and reading. TZ section 3 manifest, 15.

VK was prepared everywhere except the part that reads it: the config carried
VK_SERVICE_TOKEN, sources.source_type allowed 'vk_group', the keyword builder
produced search_queries.vk_groups, and VkAdapter could normalise a post -- but
nothing ever called the VK API. Those queries were generated for no one, and a
vk_group source was skipped by the collector without a word.
"""
import pytest

from app.collectors.vk_collector import VkCollector
from app.config import config

TOKEN = "vk-service-token"


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    monkeypatch.setattr(config, "vk_service_token", TOKEN)
    monkeypatch.setattr(config, "vk_api_version", "5.199")


class _FakeApi:
    """Stands in for api.vk.com; records calls and replays canned responses."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    async def get(self, url, params=None):
        method = url.rsplit("/", 1)[-1]
        self.calls.append((method, params))
        payload = self.responses.get(method, {"response": {"items": []}})

        class _Res:
            def raise_for_status(self):
                return None

            @staticmethod
            def json():
                return payload

        return _Res()


def _collector(responses):
    c = VkCollector()
    c._client = _FakeApi(responses)
    return c


@pytest.mark.asyncio
async def test_without_a_token_nothing_happens(monkeypatch):
    """Same contract as the Telegram collector: no credentials, no calls."""
    monkeypatch.setattr(config, "vk_service_token", None)
    c = VkCollector()

    assert c.is_available() is False
    assert await c.search_groups(["Геленджик недвижимость"]) == []
    assert await c.collect_from_source(None, None, {}) == 0


@pytest.mark.asyncio
async def test_search_returns_open_groups_with_samples():
    c = _collector({
        "groups.search": {"response": {"items": [
            {"id": 1, "screen_name": "gel_realty", "name": "Недвижимость Геленджика",
             "members_count": 4200, "is_closed": 0, "description": "Куплю-продам"},
            {"id": 2, "screen_name": "closed_club", "name": "Закрытый", "is_closed": 1},
            {"id": 3, "name": "Без адреса", "is_closed": 0},
        ]}},
        "wall.get": {"response": {"items": [
            {"text": "Ищу двухкомнатную квартиру в Геленджике до 8 млн"},
            {"text": "ок"},
            {"text": "Продаётся дом с участком, звоните по телефону"},
        ]}},
    })

    found = await c.search_groups(["Геленджик недвижимость"])

    assert [g["username"] for g in found] == ["gel_realty"], "закрытые и безымянные группы не берём"
    g = found[0]
    assert g["url"] == "https://vk.com/gel_realty"
    assert g["members"] == 4200
    # Content, not just a title: judged on its name alone the one relevant
    # Telegram chat had scored 0.
    assert len(g["samples"]) == 2
    assert all(len(s) > 20 for s in g["samples"])


@pytest.mark.asyncio
async def test_a_vk_api_error_is_not_an_exception():
    """VK answers HTTP 200 with an `error` object, so the status code says
    nothing on its own."""
    c = _collector({"groups.search": {"error": {"error_code": 5, "error_msg": "auth failed"}}})

    assert await c.search_groups(["Геленджик"]) == []


@pytest.mark.asyncio
async def test_reading_covers_comments_not_only_posts():
    """On a regional group the wall is mostly agency listings; the buyer asks
    underneath."""
    c = _collector({
        "wall.get": {"response": {"items": [
            {"id": 10, "owner_id": -55, "text": "Подборка новостроек Геленджика"},
        ]}},
        "wall.getComments": {"response": {"items": [
            {"id": 99, "from_id": 777, "text": "Куплю квартиру в Геленджике до 6 млн"},
        ]}},
    })

    entries = await c._entries([{"id": 10, "owner_id": -55, "text": "Подборка"}])

    kinds = [e["content_type"] for e in entries]
    assert kinds == ["post", "comment"]
    comment = entries[1]
    assert comment["url"] == "https://vk.com/wall-55_10?reply=99"
    assert comment["owner_id"] == -55


@pytest.mark.asyncio
async def test_the_source_handle_comes_from_the_id_or_the_url():
    class _Src:
        def __init__(self, external_id=None, source_url=""):
            self.external_id, self.source_url = external_id, source_url

    assert VkCollector._domain(_Src(external_id="gel_realty")) == "gel_realty"
    assert VkCollector._domain(_Src(source_url="https://vk.com/gel_realty")) == "gel_realty"
    assert VkCollector._domain(_Src(source_url="https://vk.com/gel_realty/")) == "gel_realty"
    assert VkCollector._domain(_Src()) is None


def test_discovery_tags_candidates_with_their_channel():
    """evaluate_and_save_sources stores vk_group vs telegram_chat from this."""
    import inspect

    from app.discovery import source_finder

    src = inspect.getsource(source_finder)
    assert '"channel": "vk"' in src
    assert '"channel": "telegram"' in src
    assert 'source_type = "vk_group" if channel == "vk" else "telegram_chat"' in src


def test_the_scheduler_runs_the_vk_collector():
    from worker.celery_app import celery_app

    tasks = {e["task"] for e in celery_app.conf.beat_schedule.values()}
    assert "worker.tasks.collector_tasks.collect_vk_sources" in tasks


# --- a pasted link decides the channel ---------------------------------------

@pytest.mark.parametrize("url,expected_type,expected_handle", [
    ("https://vk.com/gel_realty", "vk_group", "gel_realty"),
    ("https://vk.com/gel_realty/", "vk_group", "gel_realty"),
    ("vk.com/gel_realty?w=wall-1_2", "vk_group", "gel_realty"),
    ("https://t.me/gelendzhik_chat", "telegram_chat", "gelendzhik_chat"),
    ("@gelendzhik_chat", "telegram_chat", "gelendzhik_chat"),
])
def test_the_link_decides_the_channel(url, expected_type, expected_handle):
    """The add-source form sends only a link, so the type fell back to
    telegram_chat -- a VK group pasted there would have been stored as a Telegram
    chat and never read by anything."""
    from app.routers.sources import _classify

    final_url, source_type, handle = _classify(url, "telegram_chat")
    assert source_type == expected_type
    assert handle == expected_handle
    assert final_url.startswith("http")


def test_an_unrecognised_link_keeps_the_declared_type():
    from app.routers.sources import _classify

    url, source_type, handle = _classify("https://example.com/forum", "forum")
    assert (url, source_type, handle) == ("https://example.com/forum", "forum", None)
