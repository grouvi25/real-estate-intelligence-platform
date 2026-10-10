"""ТЗ «Сигналы» v1.0, апгрейд A: непрерывный автопоиск и живость источников."""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.services.discovery import rate_limit_guard as rlg
from app.services.discovery.candidate_ranker import CandidateRanker
from app.services.discovery.sandbox_tester import is_alive, verdict_for
from app.services.discovery.types import Post, SourceCandidate

db_only = pytest.mark.skipif(os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL")
NOW = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)


class _Redis:
    """fakeredis with the aclose() our code calls."""

    def __init__(self, server):
        import fakeredis.aioredis

        self._r = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)

    def __getattr__(self, name):
        return getattr(self._r, name)

    async def aclose(self):
        pass


@pytest.fixture
def redis_server(monkeypatch):
    import fakeredis

    server = fakeredis.FakeServer()
    from app.services.discovery import keyword_builder, scheduler

    factory = lambda: _Redis(server)  # noqa: E731
    monkeypatch.setattr(rlg, "redis_client", factory)
    monkeypatch.setattr(scheduler, "redis_client", factory)
    monkeypatch.setattr("app.services.discovery.rate_limit_guard.redis_client", factory)
    monkeypatch.setattr(keyword_builder, "take_queries", _all_queries)
    return server


async def _all_queries(geo_id, platform, queries, n=None):
    return list(queries[: n or 3])


def _cand(name, platform="telegram", ext=None, **kw):
    return SourceCandidate(platform=platform, external_id=ext or name.replace(" ", "_"),
                           name=name, url=f"https://t.me/{ext or name.replace(' ', '_')}", **kw)


# ---------------------------------------------------------------- unit

def test_keyword_builder_refresh_has_city_variations_and_intent_queries():
    from app.services.discovery.keyword_builder import build_matrix
    from app.services.discovery.types import TELEGRAM, YOUTUBE

    kw = build_matrix("Геленджик", {"city_variations": ["Геленджике", "Геленджика"],
                                     "search_queries": {"telegram": ["Геленджик ЖК чат"]}}, [])
    assert len(kw.city_variations) >= 3 and len(kw.intent_queries) >= 5
    assert "Геленджик ЖК чат" in kw.queries_for(TELEGRAM)
    # buyers, not renters: no rental phrasing in what we search for
    everything = " ".join(kw.intent_queries + kw.queries_for(YOUTUBE)).lower()
    assert "снять" not in everything and "аренд" not in everything


def test_sandbox_tester_verdict_thresholds():
    assert verdict_for(75, True) == "ACTIVATE"
    assert verdict_for(55, True) == "SANDBOX"
    assert verdict_for(30, True) == "REJECT"
    assert verdict_for(90, False) == "REJECT"  # silent for days: not alive


def test_alive_window_depends_on_the_platform():
    week_ago = [Post("x", NOW - timedelta(days=7))]
    assert not is_alive("telegram", week_ago, NOW)  # chats: 48 h, as in the ТЗ
    assert is_alive("youtube", week_ago, NOW)       # YouTube: 90 days
    assert is_alive("vk", [Post("обсуждение без даты")], NOW)
    assert not is_alive("telegram", [], NOW)


def test_candidate_ranker_order():
    ranker = CandidateRanker(["недвижимость"], ["Геленджик"], now=lambda: NOW)
    fresh = _cand("Недвижимость Геленджик", audience=20_000, last_post_at=NOW - timedelta(hours=2),
                  samples=["продаю квартиру недвижимость"])
    stale = _cand("Котики", audience=50, last_post_at=NOW - timedelta(days=40))
    middle = _cand("Геленджик чат", audience=3_000)
    ranked = ranker.rank([stale, middle, fresh])
    assert [c.name for c in ranked] == ["Недвижимость Геленджик", "Геленджик чат", "Котики"]
    assert all(0 <= c.rank_score <= 1 for c in ranked)


@pytest.mark.asyncio
async def test_rate_limit_guard_budget(redis_server):
    guard = rlg.RateLimitGuard({"telegram": {"daily_requests": 0}}, now=lambda: NOW.timestamp())
    assert await guard.check([_cand("a")]) == []      # budget 0: nothing passes
    assert not await guard.spend("telegram")

    yt = rlg.RateLimitGuard(now=lambda: NOW.timestamp())
    assert await yt.spend("youtube", 4000)
    assert not await yt.spend("youtube", 1001)        # over 5 000 units
    weak, strong = _cand("weak", "youtube"), _cand("strong", "youtube")
    weak.rank_score, strong.rank_score = 0.4, 0.9
    assert [c.name for c in await yt.check([weak, strong])] == ["strong"]  # 80%: economy mode


def test_parsers_of_open_platforms():
    from app.services.discovery.searchers.rss import parse_publishers
    from app.services.discovery.searchers.tg_catalog import names_city, parse_catalog
    from app.services.discovery.searchers.yandex_maps import parse_organisations

    news = """<rss><channel><item><title>Цены в Геленджике</title>
      <pubDate>Fri, 10 Oct 2026 08:00:00 GMT</pubDate>
      <source url="https://www.kuban-news.ru">Кубань Новости</source></item></channel></rss>"""
    pubs = parse_publishers(news)
    assert pubs[0]["domain"] == "kuban-news.ru" and pubs[0]["at"].year == 2026

    page = ('<a target="_blank" class="channel-name__title" href="/ru/channels/123-gel_realty">'
            'Недвижимость Геленджика</a></span><td><span class="channels-table-cursor-pointer">12 345</span>')
    assert parse_catalog(page) == [{"id": "123", "username": "gel_realty",
                                    "title": "Недвижимость Геленджика", "subscribers": 12345}]
    assert names_city("ЖК в Геленджике", ["Геленджик"]) and not names_city("Сочи", ["Геленджик"])

    body = {"features": [{"properties": {"CompanyMetaData": {"name": "Этажи"}}}]}
    assert parse_organisations(body) == ["Этажи"]


def test_settings_patch_is_validated():
    from types import SimpleNamespace

    from app.services.discovery.settings import apply_patch, discovery_settings

    agency = SimpleNamespace(settings={})
    cfg = apply_patch(agency, {"max_new_sources_per_run": 5,
                               "platform_budgets": {"youtube": {"enabled": False}}})
    assert cfg["max_new_sources_per_run"] == 5 and not cfg["platform_budgets"]["youtube"]["enabled"]
    assert discovery_settings(agency)["platform_budgets"]["telegram"]["enabled"]  # defaults kept
    for bad in ({"max_new_sources_per_run": 0}, {"sandbox_score_sandbox": 90},
                {"platform_budgets": {"myspace": {}}}, {"what": 1}):
        with pytest.raises(ValueError):
            apply_patch(agency, bad)


def test_every_ten_platforms_are_present_and_honest():
    from app.services.discovery.searchers import all_searchers

    searchers = all_searchers()
    assert len(searchers) == 10
    states = {s.platform: s.state() for s in searchers}
    assert sum(st == "active" for st in states.values()) >= 6
    assert sum(st == "stub" for st in states.values()) <= 3
    assert all(s.why_unavailable for s in searchers if s.state() != "active")


def test_robots_txt_is_honoured():
    import asyncio

    from app.services.discovery.clients import _ROBOTS, robots_allows

    class Res:
        status_code = 200
        text = "User-agent: *\nDisallow: /*search_text=\nDisallow: /private/"

    class Http:
        async def get(self, url):
            return Res()

    _ROBOTS.clear()
    assert not asyncio.run(robots_allows(Http(), "https://otzovik.example/private/x"))
    assert asyncio.run(robots_allows(Http(), "https://otzovik.example/reviews/"))


# ---------------------------------------------------------------- database

class _FakeSearcher:
    def __init__(self, platform, found, why=""):
        self.platform, self.title, self._found, self.why_unavailable = platform, platform, found, why

    def state(self):
        return "active"

    async def search(self, kw, ctx):
        return list(self._found)


class _FakeAI:
    def __init__(self, scores):
        self.scores = scores

    async def complete(self, system, user, module, agency_id="global"):
        for name, score in self.scores.items():
            if f"Название: {name}\n" in user:
                return '{"relevance_score": %d, "is_rental_focused": false}' % score
        return '{"relevance_score": 0}'

    async def close(self):
        pass


class _Clients:
    async def telegram(self):
        return object()

    def vk(self):
        return object()

    def youtube(self):
        return object()

    async def close(self):
        pass


async def _agency_with_owner(city="Геленджик"):
    from tests.helpers import unique_telegram_id

    from app.database import async_session, run_migrations
    from app.models.agency import Agency
    from app.models.geo_location import GeoLocation
    from app.models.manager import Manager

    await run_migrations()
    async with async_session() as s:
        agency = Agency(name=f"Автопоиск {uuid.uuid4().hex[:6]}", base_city=city)
        s.add(agency)
        await s.flush()
        geo = GeoLocation(agency_id=agency.id, city_name=city, geo_type="base",
                          keywords={"city_variations": [city]})
        owner = Manager(agency_id=agency.id, name="Влад", role="owner",
                        telegram_id=unique_telegram_id(), is_active=True)
        s.add_all([geo, owner])
        await s.commit()
        return agency.id, geo.id, owner.id


@db_only
@pytest.mark.asyncio
async def test_discovery_scheduler_e2e(redis_server, monkeypatch):
    """Full cycle with mock searchers: candidates, sources and a log row appear;
    the second run tests nothing twice."""
    from sqlalchemy import select

    from app.database import async_session, engine
    from app.models.agency import Agency
    from app.models.discovery import DiscoveryCandidate, DiscoveryLog
    from app.models.geo_location import GeoLocation
    from app.models.source import Source
    from app.services.discovery import sandbox_tester
    from app.services.discovery.scheduler import DiscoveryScheduler

    fresh = [Post("Ищу двушку в Геленджике до 9 млн, кто подскажет район?", NOW)]

    async def posts(clients, platform, ref, n=20):
        return None if "dead" in ref else [Post(p.text, datetime.now(timezone.utc)) for p in fresh]

    monkeypatch.setattr(sandbox_tester, "fetch_posts", posts)
    tag = uuid.uuid4().hex[:6]
    found = [_cand(f"Недвижимость Геленджик {tag}"), _cand(f"Геленджик болталка {tag}"),
             _cand(f"Котики {tag}"), _cand(f"dead {tag}")]
    ai = _FakeAI({found[0].name: 85, found[1].name: 50, found[2].name: 10, found[3].name: 99})
    try:
        agency_id, geo_id, _ = await _agency_with_owner()
        for _ in range(2):
            async with async_session() as s:
                agency, geo = await s.get(Agency, agency_id), await s.get(GeoLocation, geo_id)
                report = await DiscoveryScheduler(
                    s, agency, geo, searchers=[_FakeSearcher("telegram", found)],
                    clients=_Clients(), ai=ai).run()
            if _ == 0:
                first = report
        async with async_session() as s:
            cands = {c.name: c for c in (await s.execute(select(DiscoveryCandidate).where(
                DiscoveryCandidate.agency_id == agency_id))).scalars()}
            sources = {x.source_name: x for x in (await s.execute(select(Source).where(
                Source.agency_id == agency_id))).scalars()}
            logs = (await s.execute(select(DiscoveryLog).where(
                DiscoveryLog.agency_id == agency_id))).scalars().all()
    finally:
        await engine.dispose()

    assert (first.found, first.tested, first.activated, first.sandboxed, first.rejected) == (4, 4, 1, 1, 2)
    assert report.tested == 0  # nothing is tested twice
    assert cands[found[0].name].verdict == "ACTIVATE" and cands[found[1].name].verdict == "SANDBOX"
    assert cands[found[1].name].retry_after is not None
    assert cands[found[3].name].verdict == "REJECT" and cands[found[3].name].is_alive is False
    assert sources[found[0].name].status == "active" and sources[found[0].name].discovered_by == "discovery"
    assert sources[found[0].name].geo_location_id == geo_id
    assert sources[found[1].name].status == "sandbox"
    assert found[2].name not in sources and found[3].name not in sources  # rejected: not deleted, not a source
    assert len(logs) == 2 and logs[0].found == 4


@db_only
@pytest.mark.asyncio
async def test_duplicate_filter_exact_and_fuzzy():
    from app.database import async_session, engine
    from app.models.source import Source
    from app.services.discovery.duplicate_filter import DuplicateFilter

    try:
        agency_id, geo_id, _ = await _agency_with_owner()
        async with async_session() as s:
            s.add(Source(agency_id=agency_id, geo_location_id=geo_id, source_type="telegram_chat",
                         source_url="https://t.me/gel_realty", external_id="gel_realty",
                         source_name="Недвижимость Геленджик | Чат"))
            await s.commit()
            out = await DuplicateFilter(s, agency_id).check([
                _cand("Что-то другое", ext="Gel_Realty"),            # same handle, other case
                _cand("Недвижимость Геленджик чат", ext="new_one"),   # 90%+ the same name
                _cand("Анапа переезд", ext="anapa_move"),
                _cand("Анапа переезд", platform="tg_catalog", ext="anapa_move"),  # same channel twice
            ])
    finally:
        await engine.dispose()
    assert [c.external_id for c in out] == ["anapa_move"]


@db_only
@pytest.mark.asyncio
async def test_health_check_dead_source_is_disabled_after_three_failures(monkeypatch):
    from app.database import async_session, engine
    from app.models.source import Source
    from app.services.discovery import health

    told = []

    async def notify(session, agency_id, sources):
        told.extend(s.source_name for s in sources)

    monkeypatch.setattr(health, "_notify_owners", notify)

    class Guard:
        async def spend(self, platform, cost=1):
            return True

    async def posts(clients, platform, ref, n=5):
        return None if ref.startswith("gone") else [Post("жив", NOW - timedelta(hours=1))]

    monkeypatch.setattr(health, "fetch_posts", posts)
    try:
        agency_id, geo_id, _ = await _agency_with_owner()
        async with async_session() as s:
            gone = Source(agency_id=agency_id, geo_location_id=geo_id, source_type="telegram_chat",
                          source_url="https://t.me/gone_chat", external_id="gone_chat",
                          source_name="Удалённый чат", status="active")
            alive = Source(agency_id=agency_id, geo_location_id=geo_id, source_type="telegram_chat",
                           source_url="https://t.me/alive_a", external_id="alive_a", status="active")
            alive2 = Source(agency_id=agency_id, geo_location_id=geo_id, source_type="telegram_chat",
                            source_url="https://t.me/alive_b", external_id="alive_b", status="active")
            s.add_all([gone, alive, alive2])
            await s.commit()
            for _ in range(3):
                await health.check_sources(s, [gone, alive, alive2], _Clients(), Guard(), now=NOW)
            assert gone.status == "disabled" and gone.consecutive_failures == 3
            assert alive.health_status == "healthy" and alive.consecutive_failures == 0
            assert told == ["Удалённый чат"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_platform_outage_is_not_counted_against_its_sources(monkeypatch):
    from types import SimpleNamespace

    from app.services.discovery import health

    async def posts(*a, **k):
        return None  # every Telegram source unreadable at once: Telegram is down

    monkeypatch.setattr(health, "fetch_posts", posts)

    class Guard:
        async def spend(self, platform, cost=1):
            return True

    class Session:
        async def commit(self):
            pass

    sources = [SimpleNamespace(id=i, agency_id="a", source_type="telegram_chat", status="active",
                               external_id=f"chat{i}", source_url=f"https://t.me/chat{i}",
                               consecutive_failures=2, health_status="dead",
                               last_health_check=None, last_post_at=None) for i in range(4)]
    counts = await health.check_sources(Session(), sources, _Clients(), Guard(), now=NOW)
    assert counts == {"skipped": 4}
    assert all(s.status == "active" and s.consecutive_failures == 2 for s in sources)


@db_only
@pytest.mark.asyncio
async def test_owner_overrules_discovery_and_sets_it_up():
    from app.database import async_session, engine
    from app.dependencies import CurrentManager
    from app.exceptions import AppException
    from app.models.discovery import DiscoveryCandidate
    from app.models.source import Source
    from app.routers import discovery as r

    try:
        agency_id, geo_id, owner_id = await _agency_with_owner()
        ctx = CurrentManager(str(owner_id), str(agency_id))
        async with async_session() as s:
            rejected = DiscoveryCandidate(agency_id=agency_id, geo_location_id=geo_id, platform="vk",
                                          external_id="gel_vk", name="Геленджик ВК",
                                          url="https://vk.com/gel_vk", verdict="REJECT",
                                          sandbox_score=35, raw_meta={"vk_group_id": 42})
            org = DiscoveryCandidate(agency_id=agency_id, platform="yandex_maps", external_id="x",
                                     verdict="REJECT")
            s.add_all([rejected, org])
            await s.commit()
        async with async_session() as s:
            out = await r.activate_candidate(rejected.id, current=ctx, session=s)
            src = await s.get(Source, uuid.UUID(out["source_id"]))
            assert (out["verdict"], out["decided_by"]) == ("ACTIVATE", "manager")
            assert src.status == "active" and src.source_type == "vk_group"
            assert src.external_id == "gel_vk" and src.meta.get("vk_group_id") == 42
            with pytest.raises(AppException):
                await r.activate_candidate(org.id, current=ctx, session=s)  # not a source
            await r.reject_candidate(rejected.id, current=ctx, session=s)
            await s.refresh(src)
            assert src.status == "paused"  # kept, not deleted
            listed = await r.list_candidates(verdict="REJECT", platform=None, limit=100,
                                             current=ctx, session=s)
            assert listed["count"] == 2
            cfg = await r.patch_config({"enabled": False}, current=ctx, session=s)
            assert cfg["config"]["enabled"] is False and len(cfg["platforms"]) == 10
            with pytest.raises(AppException):
                await r.patch_config({"run_interval_minutes": 5}, current=ctx, session=s)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_telethon_lock_lets_one_holder_at_a_time(monkeypatch):
    import fakeredis

    from app.collectors import telethon_sessions

    server = fakeredis.FakeServer()

    async def factory():
        return _Redis(server)

    monkeypatch.setattr(telethon_sessions, "_redis", factory)
    async with telethon_sessions.telethon_lock(wait_seconds=0) as first:
        async with telethon_sessions.telethon_lock(wait_seconds=0) as second:
            assert first is True and second is False
    async with telethon_sessions.telethon_lock(wait_seconds=0) as again:
        assert again is True  # released on exit


def test_discovery_beat_and_queue():
    from worker.celery_app import celery_app

    beat = celery_app.conf.beat_schedule
    assert beat["discovery-hourly"]["task"] == "worker.tasks.discovery.run_discovery_for_all_agencies"
    assert beat["source-health-check"]["task"] == "worker.tasks.discovery.check_source_health"
    assert beat["discovery-sandbox-retry"]["task"] == "worker.tasks.discovery.retry_sandbox_candidates"
    assert "geo-discovery-weekly" not in beat
    routes = celery_app.conf.task_routes
    assert routes["worker.tasks.discovery.*"]["queue"] == "discovery"
    from pathlib import Path

    compose = (Path(__file__).resolve().parent.parent / "docker-compose.yml").read_text(encoding="utf-8")
    assert "-Q celery,discovery" in compose  # someone has to consume the queue
