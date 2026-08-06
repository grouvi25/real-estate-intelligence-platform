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


@pytest.mark.asyncio
async def test_a_service_key_can_read_walls_even_if_it_cannot_search():
    """VK's own schema: wall.get and wall.getComments accept a service token,
    groups.search is user-only. A service key is therefore a supported way to
    run -- add the groups by hand, and reading works."""
    c = _collector({
        "groups.search": {"error": {"error_code": 28,
                                    "error_msg": "Application authorization failed"}},
        "wall.get": {"response": {"items": [
            {"id": 1, "owner_id": -55, "text": "Ищу квартиру в Геленджике до 7 млн"},
        ]}},
    })

    assert await c.search_groups(["Геленджик"]) == []
    entries = await c._entries([{"id": 1, "owner_id": -55, "text": "Ищу квартиру"}])
    assert entries and entries[0]["content_type"] == "post"


@pytest.mark.parametrize("code", [5, 15, 28])
def test_a_too_weak_token_is_recognised(code):
    """Checked against the live API with a real service token: groups.search
    answers 15 "Access denied", not the 28 the schema implied."""
    from app.collectors.vk_collector import TOKEN_TOO_WEAK

    assert code in TOKEN_TOO_WEAK


# --- a disabled wall is not a dead group -------------------------------------

class _Src:
    def __init__(self, external_id="gel_baraholka", meta=None):
        self.external_id, self.source_url, self.meta = external_id, "", meta or {}


@pytest.mark.asyncio
async def test_board_topics_are_read_when_the_wall_is_off():
    """Both Геленджик classified groups answered wall.get with
    "Access denied: wall is disabled" -- their listings live in обсуждения."""
    c = _collector({
        "wall.get": {"error": {"error_code": 15, "error_msg": "Access denied: wall is disabled"}},
        "groups.getById": {"response": {"groups": [{"id": 57812686}]}},
        "board.getTopics": {"response": {"items": [{"id": 7, "title": "Куплю"}]}},
        "board.getComments": {"response": {"items": [
            {"id": 42, "from_id": 900, "text": "Куплю двушку в Геленджике до 8 млн"},
        ]}},
    })

    entries = await c._board_entries(_Src())

    assert len(entries) == 1
    assert entries[0]["content_type"] == "comment"
    assert entries[0]["url"] == "https://vk.com/topic-57812686_7?post=42"
    assert entries[0]["owner_id"] == -57812686


@pytest.mark.asyncio
async def test_a_known_group_id_skips_the_lookup():
    c = _collector({
        "board.getTopics": {"response": {"items": []}},
    })

    assert await c._group_id(_Src(meta={"vk_group_id": 123})) == 123
    assert "groups.getById" not in [m for m, _ in c._client.calls]


# --- discovery without groups.search -----------------------------------------

def _feed_responses(items, groups):
    return {
        "groups.search": {"error": {"error_code": 15, "error_msg": "Access denied"}},
        "newsfeed.search": {"response": {"items": items}},
        "groups.getById": {"response": {"groups": groups}},
    }


@pytest.mark.asyncio
async def test_the_feed_finds_groups_when_the_directory_is_closed():
    """groups.search is user-only, but newsfeed.search takes a service key and
    every post names its publisher -- so the groups can be counted out of the
    feed. Measured live on Геленджик: five queries, 103 groups, every large
    local барахолка among them."""
    c = _collector(_feed_responses(
        items=[
            {"owner_id": -20096, "text": "Куплю квартиру в Геленджике"},
            {"owner_id": -20096, "text": "Продам дом"},
            {"owner_id": 777, "text": "личная страница, не группа"},
        ],
        groups=[{"id": 20096, "screen_name": "aviyla", "members_count": 20096,
                 "name": "Барахолка|Куплю|Продам|Геленджик", "is_closed": 0}],
    ))

    found = await c.search_groups(["Геленджик квартира"])

    assert [g["username"] for g in found] == ["aviyla"]
    assert found[0]["members"] == 20096
    counted = [p for m, p in c._client.calls if m == "groups.getById"]
    assert "777" not in counted[0]["group_ids"], "положительный owner_id — это человек, не группа"


@pytest.mark.asyncio
async def test_the_feed_is_not_used_when_the_directory_answers():
    """A user token searches properly; the looser feed path must stay off."""
    c = _collector({
        "groups.search": {"response": {"items": [
            {"id": 1, "screen_name": "gel_realty", "name": "Недвижимость", "is_closed": 0},
        ]}},
    })

    await c.search_groups(["Геленджик недвижимость"])

    assert "newsfeed.search" not in [m for m, _ in c._client.calls]


@pytest.mark.asyncio
async def test_the_feed_drags_in_strangers_and_they_are_dropped():
    """"Новости Тольятти" really did answer "Геленджик квартира", and a tiny
    group is not worth the AI call either."""
    c = _collector(_feed_responses(
        items=[{"owner_id": -1}, {"owner_id": -2}, {"owner_id": -3}],
        groups=[
            {"id": 1, "screen_name": "t0lyatt1", "members_count": 1614,
             "name": "Новости Тольятти сегодня", "is_closed": 0},
            {"id": 2, "screen_name": "tiny_gel", "members_count": 40,
             "name": "Геленджик квартиры", "is_closed": 0},
            {"id": 3, "screen_name": "closed_gel", "members_count": 9000,
             "name": "Геленджик недвижимость", "is_closed": 1},
        ],
    ))

    assert await c.search_groups(["Геленджик квартира"]) == []


def test_a_search_word_matches_the_declined_form():
    """«Барахолка Геленджика» has to match the query «Геленджик квартира»."""
    from app.collectors.vk_collector import VkCollector

    stems = VkCollector._stems(["Геленджик куплю квартиру"])

    text = "барахолка геленджика: квартиры и дома".lower()
    assert any(s in text for s in stems)
    assert not any(s in "новости тольятти сегодня" for s in stems)


@pytest.mark.asyncio
async def test_a_group_with_neither_wall_nor_topics_yields_nothing():
    c = _collector({
        "wall.get": {"error": {"error_code": 15, "error_msg": "Access denied: wall is disabled"}},
        "groups.getById": {"response": {"groups": [{"id": 1}]}},
        "board.getTopics": {"response": {"items": []}},
    })

    assert await c._board_entries(_Src()) == []


@pytest.mark.asyncio
async def test_a_candidate_with_a_closed_wall_is_still_sampled():
    """The groups most worth having are the ones with no wall: both Геленджик
    барахолки answer "wall is disabled". Judged on a bare name the one relevant
    Telegram chat had scored 0 -- these would reach the AI the same way."""
    c = _collector({
        "wall.get": {"error": {"error_code": 15, "error_msg": "Access denied: wall is disabled"}},
        "groups.getById": {"response": {"groups": [{"id": 57812686}]}},
        "board.getTopics": {"response": {"items": [{"id": 7, "title": "Куплю"}]}},
        "board.getComments": {"response": {"items": [
            {"id": 42, "text": "Куплю двушку в Геленджике до 8 млн, наличка"},
            {"id": 43, "text": "ок"},
        ]}},
    })
    cand = {"username": "gel_baraholka", "samples": []}

    await c._enrich([cand])

    assert cand["samples"] == ["Куплю двушку в Геленджике до 8 млн, наличка"]
