"""Monitoring source management endpoint tests (need PostgreSQL). TZ 30, 15.

Discovery writes sources and the collector reads them; this router is the only
way to see what the engine picked and to stop a bad source without an UPDATE
against the database.
"""
import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL"
)


async def _agency_with_geo(s):
    from app.models.agency import Agency
    from app.models.geo_location import GeoLocation

    agency = Agency(name="Sources Agency", base_city="Геленджик")
    s.add(agency)
    await s.flush()
    geo = GeoLocation(agency_id=agency.id, city_name="Геленджик", geo_type="sales")
    s.add(geo)
    await s.flush()
    return agency, geo


async def _current(s, agency):
    """Владелец агентства — настоящей строкой в базе, не выдуманным id.

    Мутации источников защищены require_owner: она читает менеджера из базы и
    требует роль owner. Пока тесты подставляли случайный uuid, строки не
    находилось и любая правка источника отвечала 403.
    """
    from app.dependencies import CurrentManager
    from app.models.manager import Manager

    manager = Manager(agency_id=agency.id, name="Владелец", role="owner")
    s.add(manager)
    await s.commit()
    return CurrentManager(manager_id=str(manager.id), agency_id=str(agency.id))


@pytest.mark.asyncio
async def test_add_source_by_username_and_list_it():
    from app.database import async_session, run_migrations
    from app.routers.sources import CreateSourceRequest, create_source, list_sources

    await run_migrations()
    async with async_session() as s:
        agency, geo = await _agency_with_geo(s)
        await s.commit()
        current = await _current(s, agency)

    async with async_session() as s:
        created = await create_source(
            CreateSourceRequest(source_url="@gelendzhik_chat", geo_location_id=geo.id),
            current=current, session=s)

    # "@name" is normalised to a t.me URL, and the username is stored in
    # external_id because that is what the collector resolves sources by.
    assert created["source_url"] == "https://t.me/gelendzhik_chat"
    assert created["external_id"] == "gelendzhik_chat"
    assert created["status"] == "sandbox"
    assert created["auto_found"] is False

    async with async_session() as s:
        listed = await list_sources(current=current, session=s)
    assert listed["count"] == 1
    assert listed["sources"][0]["city_name"] == "Геленджик"


@pytest.mark.asyncio
async def test_duplicate_source_is_rejected():
    from app.database import async_session, run_migrations
    from app.exceptions import ValidationError
    from app.routers.sources import CreateSourceRequest, create_source

    await run_migrations()
    async with async_session() as s:
        agency, _ = await _agency_with_geo(s)
        await s.commit()
        current = await _current(s, agency)

    async with async_session() as s:
        await create_source(CreateSourceRequest(source_url="https://t.me/dup_chat"),
                            current=current, session=s)
        with pytest.raises(ValidationError):
            await create_source(CreateSourceRequest(source_url="https://t.me/dup_chat"),
                                current=current, session=s)


@pytest.mark.asyncio
async def test_pause_a_source_so_the_collector_skips_it():
    """The live rental chat had to be paused with raw SQL; this is the fix."""
    from app.database import async_session, run_migrations
    from app.routers.sources import (
        CreateSourceRequest,
        UpdateSourceRequest,
        create_source,
        list_sources,
        update_source,
    )

    await run_migrations()
    async with async_session() as s:
        agency, _ = await _agency_with_geo(s)
        await s.commit()
        current = await _current(s, agency)

    async with async_session() as s:
        created = await create_source(
            CreateSourceRequest(source_url="https://t.me/rental_chat", status="active"),
            current=current, session=s)
        updated = await update_source(uuid.UUID(created["id"]),
                                      UpdateSourceRequest(status="paused"),
                                      current=current, session=s)
        assert updated["status"] == "paused"

    async with async_session() as s:
        # The collector only reads active/sandbox.
        active = await list_sources(status="active", current=current, session=s)
        assert active["count"] == 0
        paused = await list_sources(status="paused", current=current, session=s)
        assert paused["count"] == 1


@pytest.mark.asyncio
async def test_delete_is_blocked_while_signals_reference_the_source():
    from app.database import async_session, run_migrations
    from app.exceptions import AppException
    from app.models.signal import Signal
    from app.routers.sources import CreateSourceRequest, create_source, delete_source

    await run_migrations()
    async with async_session() as s:
        agency, _ = await _agency_with_geo(s)
        await s.commit()
        current = await _current(s, agency)

    async with async_session() as s:
        created = await create_source(CreateSourceRequest(source_url="https://t.me/busy_chat"),
                                      current=current, session=s)
        s.add(Signal(agency_id=agency.id, source_id=uuid.UUID(created["id"]),
                     raw_text="Куплю квартиру в Геленджике"))
        await s.commit()

    async with async_session() as s:
        with pytest.raises(AppException) as e:
            await delete_source(uuid.UUID(created["id"]), current=current, session=s)
        # Deleting would break v_signal_to_outcome attribution and Source ROI.
        assert e.value.status_code == 409


@pytest.mark.asyncio
async def test_delete_removes_a_source_with_no_signals():
    from app.database import async_session, run_migrations
    from app.routers.sources import CreateSourceRequest, create_source, delete_source, list_sources

    await run_migrations()
    async with async_session() as s:
        agency, _ = await _agency_with_geo(s)
        await s.commit()
        current = await _current(s, agency)

    async with async_session() as s:
        created = await create_source(CreateSourceRequest(source_url="https://t.me/empty_chat"),
                                      current=current, session=s)
        res = await delete_source(uuid.UUID(created["id"]), current=current, session=s)
        assert res["deleted"] is True

    async with async_session() as s:
        assert (await list_sources(current=current, session=s))["count"] == 0


@pytest.mark.asyncio
async def test_sources_are_scoped_to_the_token_agency():
    from app.database import async_session, run_migrations
    from app.exceptions import NotFoundError
    from app.models.agency import Agency
    from app.routers.sources import (
        CreateSourceRequest,
        UpdateSourceRequest,
        create_source,
        list_sources,
        update_source,
    )

    await run_migrations()
    async with async_session() as s:
        agency, _ = await _agency_with_geo(s)
        other = Agency(name="Other Sources Agency", base_city="Сочи")
        s.add(other)
        await s.commit()
        current, stranger = await _current(s, agency), await _current(s, other)

    async with async_session() as s:
        created = await create_source(CreateSourceRequest(source_url="https://t.me/scoped_chat"),
                                      current=current, session=s)

    async with async_session() as s:
        assert (await list_sources(current=stranger, session=s))["count"] == 0
        with pytest.raises(NotFoundError):
            await update_source(uuid.UUID(created["id"]), UpdateSourceRequest(status="active"),
                                current=stranger, session=s)


@pytest.mark.asyncio
async def test_rejects_invalid_type_status_and_score():
    from app.database import async_session, run_migrations
    from app.exceptions import ValidationError
    from app.routers.sources import (
        CreateSourceRequest,
        UpdateSourceRequest,
        create_source,
        update_source,
    )

    await run_migrations()
    async with async_session() as s:
        agency, _ = await _agency_with_geo(s)
        await s.commit()
        current = await _current(s, agency)

    async with async_session() as s:
        with pytest.raises(ValidationError):
            await create_source(CreateSourceRequest(source_url="https://t.me/x", source_type="carrier_pigeon"),
                                current=current, session=s)
        with pytest.raises(ValidationError):
            await create_source(CreateSourceRequest(source_url="https://t.me/x", status="nonsense"),
                                current=current, session=s)
        with pytest.raises(ValidationError):
            await create_source(CreateSourceRequest(source_url="   "), current=current, session=s)

        created = await create_source(CreateSourceRequest(source_url="https://t.me/score_chat"),
                                      current=current, session=s)
        with pytest.raises(ValidationError):
            await update_source(uuid.UUID(created["id"]), UpdateSourceRequest(score=500),
                                current=current, session=s)


@pytest.mark.asyncio
async def test_a_source_added_without_a_city_gets_the_agency_s_own():
    """A source with no geo is inert: the collectors take their pre-filter
    keywords from the geo, an empty set fails the city check, and every message
    is discarded. It looks active on the screen and never produces a signal. The
    add form does not ask for a city, so the single obvious one is filled in."""
    from app.database import async_session, run_migrations
    from app.routers.sources import CreateSourceRequest, create_source

    await run_migrations()
    async with async_session() as s:
        agency, geo = await _agency_with_geo(s)
        await s.commit()
        current, geo_id = await _current(s, agency), geo.id

    async with async_session() as s:
        created = await create_source(
            CreateSourceRequest(source_url="https://vk.com/gel_baraholka"),
            current=current, session=s)

    assert created["geo_location_id"] == str(geo_id)
    assert created["source_type"] == "vk_group"


@pytest.mark.asyncio
async def test_with_two_cities_the_source_must_name_one():
    from app.database import async_session, run_migrations
    from app.exceptions import ValidationError
    from app.models.geo_location import GeoLocation
    from app.routers.sources import CreateSourceRequest, create_source

    await run_migrations()
    async with async_session() as s:
        agency, _ = await _agency_with_geo(s)
        s.add(GeoLocation(agency_id=agency.id, city_name="Анапа", geo_type="sales"))
        await s.commit()
        current = await _current(s, agency)

    async with async_session() as s:
        with pytest.raises(ValidationError):
            await create_source(CreateSourceRequest(source_url="@two_cities_chat"),
                                current=current, session=s)


@pytest.mark.asyncio
async def test_an_agency_with_no_city_is_told_to_add_one():
    from app.database import async_session, run_migrations
    from app.exceptions import ValidationError
    from app.models.agency import Agency
    from app.routers.sources import CreateSourceRequest, create_source

    await run_migrations()
    async with async_session() as s:
        agency = Agency(name=f"No geo {uuid.uuid4().hex[:6]}", base_city="Геленджик")
        s.add(agency)
        await s.commit()
        current = await _current(s, agency)

    async with async_session() as s:
        with pytest.raises(ValidationError):
            await create_source(CreateSourceRequest(source_url="@no_geo_chat"),
                                current=current, session=s)


def test_a_link_says_which_kind_of_source_it_is():
    """The form sends a link and nothing else, so the link has to be read.

    Before this, anything that was not VK or Telegram was stored as a Telegram
    chat: the YouTube and RSS collectors existed while there was no way to add a
    source either of them would ever look at.
    """
    from app.routers.sources import _classify

    cases = [
        ("vk.com/gel_realty", "vk_group", "gel_realty"),
        ("@gelendzhik_chat", "telegram_chat", "gelendzhik_chat"),
        ("https://t.me/gel_news", "telegram_chat", "gel_news"),
        ("https://youtube.com/@novostroyki", "youtube", None),
        ("https://www.youtube.com/channel/UC123abc/videos", "youtube", "UC123abc"),
        ("https://youtu.be/abc", "youtube", None),
        ("https://kubnews.ru/rss/", "rss", None),
        ("https://gelendzhik.ru/news/feed", "rss", None),
        ("https://example.ru/index.xml", "rss", None),
        ("https://forum-gelendzhik.ru/threads/", "website", None),
    ]
    for url, kind, handle in cases:
        _, got_kind, got_handle = _classify(url, "telegram_chat")
        assert got_kind == kind, f"{url}: ожидался {kind}, вышел {got_kind}"
        assert got_handle == handle, f"{url}: ожидался идентификатор {handle}, вышел {got_handle}"


def test_an_explicit_type_beats_the_guess():
    """A manager who knows it is a forum should not be overruled by the URL."""
    from app.routers.sources import _classify

    _, kind, _ = _classify("https://forum-gelendzhik.ru/threads/", "forum")
    assert kind == "forum"


def test_every_source_type_is_read_by_some_collector():
    """A type the schema allows and nothing collects is a source that sits for
    ever — exactly what happened to rss and website before the web collector."""
    import re
    from pathlib import Path

    from app.routers.sources import SOURCE_TYPES

    root = Path(__file__).resolve().parent.parent
    web = (root / "worker" / "tasks" / "collector_tasks.py").read_text(encoding="utf-8")
    listed = re.findall(r"'(\w+)'|\"(\w+)\"", web.split("by_type = {")[1].split("}")[0])
    collected = {a or b for a, b in listed}
    collected |= {"telegram_chat", "telegram_channel"}   # collect_telegram_sources
    collected |= {"vk_group"}                            # collect_vk_sources

    orphans = SOURCE_TYPES - collected
    assert orphans == set(), f"эти типы никто не собирает: {orphans}"


def _collector_configured(monkeypatch):
    """The collector has its credentials.

    conftest pins every optional credential to absent, which is the honest
    default -- but it also means a channel reads as "выключен" and the verdict
    becomes "канал не настроен" before it ever looks at the numbers. A test
    about yield has to say that the collector is running.
    """
    from app.config import config

    monkeypatch.setattr(config, "telethon_api_id", 1, raising=False)
    monkeypatch.setattr(config, "telethon_api_hash", "hash", raising=False)


async def _seed_collection(s, agency, geo, *, messages: int, signals: int, status="sandbox"):
    """A week's worth of reading, with however much of it looked promising."""
    from app.models.content_unit import ContentUnit
    from app.models.signal import Signal
    from app.models.source import Source

    src = Source(agency_id=agency.id, geo_location_id=geo.id, source_type="telegram_chat",
                 source_url="https://t.me/chat", external_id="chat", status=status)
    s.add(src)
    await s.flush()
    for i in range(messages):
        s.add(ContentUnit(agency_id=agency.id, source_id=src.id, channel="telegram",
                          external_id=f"m{i}", raw_content="текст"))
    for i in range(signals):
        s.add(Signal(agency_id=agency.id, source_id=src.id, geo_location_id=geo.id,
                     raw_text="ищу квартиру", status="new"))
    await s.commit()
    return src


@pytest.mark.asyncio
async def test_a_trickle_of_signals_is_reported_as_a_problem_not_as_health(monkeypatch):
    """Two signals out of two thousand messages is the problem, not the norm.

    Live, the collector read 2050 messages in a week and produced 2 signals, and
    every screen said "нет сигналов" -- which reads as "wait a bit longer". It
    is not: at that yield the chats are the suspect.
    """
    from app.database import async_session, run_migrations
    from app.routers.sources import collection_status

    _collector_configured(monkeypatch)
    await run_migrations()
    async with async_session() as s:
        agency, geo = await _agency_with_geo(s)
        await s.commit()
        current = await _current(s, agency)
        await _seed_collection(s, agency, geo, messages=400, signals=1)

    async with async_session() as s:
        d = await collection_status(current=current, session=s)

    assert d["verdict"]["tone"] == "warning"
    assert "чаты не те" in d["verdict"]["action"]
    assert d["collected"]["week"] == 400
    assert d["signals"]["week"] == 1


@pytest.mark.asyncio
async def test_a_working_yield_is_left_alone(monkeypatch):
    from app.database import async_session, run_migrations
    from app.routers.sources import collection_status

    _collector_configured(monkeypatch)
    await run_migrations()
    async with async_session() as s:
        agency, geo = await _agency_with_geo(s)
        await s.commit()
        current = await _current(s, agency)
        await _seed_collection(s, agency, geo, messages=400, signals=8)

    async with async_session() as s:
        d = await collection_status(current=current, session=s)
    assert d["verdict"]["tone"] == "ok"


@pytest.mark.asyncio
async def test_a_paused_source_means_nothing_is_being_read(monkeypatch):
    """Sources that exist but are all stopped is a different answer again."""
    from app.database import async_session, run_migrations
    from app.routers.sources import collection_status

    _collector_configured(monkeypatch)
    await run_migrations()
    async with async_session() as s:
        agency, geo = await _agency_with_geo(s)
        await s.commit()
        current = await _current(s, agency)
        await _seed_collection(s, agency, geo, messages=0, signals=0, status="paused")

    async with async_session() as s:
        d = await collection_status(current=current, session=s)

    assert d["verdict"]["tone"] == "blocker"
    telegram = next(c for c in d["channels"] if c["key"] == "telegram")
    assert telegram["sources"] == 1 and telegram["working"] == 0
