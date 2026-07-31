"""Source Discovery tests: search stub, AI evaluation + save, cron wiring."""
import os

import pytest


@pytest.mark.asyncio
async def test_search_returns_empty_without_telethon():
    from app.discovery.source_finder import search_telegram_sources

    assert await search_telegram_sources({"city_variations": ["Геленджик"]}) == []


@pytest.mark.skipif(os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL")
@pytest.mark.asyncio
async def test_evaluate_and_save_sources(monkeypatch):
    from sqlalchemy import select

    from app.database import async_session, run_migrations
    from app.discovery.source_finder import evaluate_and_save_sources
    from app.models.agency import Agency
    from app.models.geo_location import GeoLocation
    from app.models.source import Source
    from app.services.ai_service import AIService

    async def fake_complete(self, system, user, module, agency_id="global"):
        if "GoodChat" in user:
            return '{"relevance_score": 85}'
        if "OkChat" in user:
            return '{"relevance_score": 55}'
        return '{"relevance_score": 10}'

    monkeypatch.setattr(AIService, "complete", fake_complete)
    await run_migrations()
    async with async_session() as s:
        agency = Agency(name="Discovery Agency", base_city="Геленджик")
        s.add(agency)
        await s.flush()
        geo = GeoLocation(agency_id=agency.id, city_name="Геленджик", geo_type="base")
        s.add(geo)
        await s.commit()
        geo_id, agency_id = geo.id, agency.id

    candidates = [
        {"name": "GoodChat Геленджик", "username": "goodchat", "members": 5000},
        {"name": "OkChat", "username": "okchat", "members": 800},
        {"name": "BadChat", "username": "badchat", "members": 10},
    ]
    async with async_session() as s:
        saved = await evaluate_and_save_sources(
            s, candidates, geo_id, {"agency_id": agency_id, "city_name": "Геленджик"}
        )
    assert saved == 2  # active + sandbox; bad (score 10) skipped

    async with async_session() as s:
        sources = (
            await s.execute(select(Source).where(Source.geo_location_id == geo_id))
        ).scalars().all()
        assert sorted(x.status for x in sources) == ["active", "sandbox"]
        assert all(x.auto_found for x in sources)


@pytest.mark.skipif(os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL")
@pytest.mark.asyncio
async def test_geo_discovery_cron_runs():
    from app.database import run_migrations
    from worker.tasks.source_tasks import _geo_discovery_cron

    await run_migrations()
    # search_telegram_sources returns [] (no Telethon) -> nothing saved, no error.
    assert await _geo_discovery_cron() == 0


@pytest.mark.skipif(os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL")
@pytest.mark.asyncio
async def test_discovery_does_not_duplicate_a_source_it_refinds(monkeypatch):
    """Discovery runs weekly over the same city and re-finds the same chats.
    Without an upsert every run added another copy -- production ended up with
    "Барахолка Геленджик" twice after two sweeps."""
    from app.database import async_session, run_migrations
    from app.discovery.source_finder import evaluate_and_save_sources
    from app.models.agency import Agency
    from app.models.source import Source
    from app.services.ai_service import AIService
    from sqlalchemy import func, select

    async def fake_complete(self, system, user, module, agency_id="global"):
        return '{"relevance_score": 55}'

    monkeypatch.setattr(AIService, "complete", fake_complete)
    await run_migrations()

    async with async_session() as s:
        agency = Agency(name="Dedup Agency", base_city="Геленджик")
        s.add(agency)
        await s.commit()
        agency_id = agency.id

    candidates = [{"id": "123", "name": "Барахолка Геленджик",
                   "username": "barahol_gel", "url": "https://t.me/barahol_gel"}]
    profile = {"agency_id": agency_id, "city_name": "Геленджик"}

    async with async_session() as s:
        first = await evaluate_and_save_sources(s, candidates, None, profile)
    async with async_session() as s:
        second = await evaluate_and_save_sources(s, candidates, None, profile)

    assert first == 1
    assert second == 0  # re-found, not re-added

    async with async_session() as s:
        count = await s.scalar(
            select(func.count()).select_from(Source).where(Source.agency_id == agency_id))
    assert count == 1


@pytest.mark.skipif(os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL")
@pytest.mark.asyncio
async def test_refinding_a_paused_source_does_not_reactivate_it(monkeypatch):
    """A manager pausing a bad source must stick -- otherwise the next sweep
    quietly puts it back to work."""
    from app.database import async_session, run_migrations
    from app.discovery.source_finder import evaluate_and_save_sources
    from app.models.agency import Agency
    from app.models.source import Source
    from app.services.ai_service import AIService
    from sqlalchemy import select

    async def fake_complete(self, system, user, module, agency_id="global"):
        return '{"relevance_score": 85}'

    monkeypatch.setattr(AIService, "complete", fake_complete)
    await run_migrations()

    async with async_session() as s:
        agency = Agency(name="Paused Agency", base_city="Геленджик")
        s.add(agency)
        await s.flush()
        s.add(Source(agency_id=agency.id, source_type="telegram_chat",
                     source_url="https://t.me/rental_chat", source_name="Аренда",
                     status="paused", score=15))
        await s.commit()
        agency_id = agency.id

    async with async_session() as s:
        await evaluate_and_save_sources(
            s, [{"id": "9", "name": "Аренда", "username": "rental_chat",
                 "url": "https://t.me/rental_chat"}],
            None, {"agency_id": agency_id, "city_name": "Геленджик"})

    async with async_session() as s:
        source = (await s.execute(
            select(Source).where(Source.agency_id == agency_id))).scalars().one()
    assert source.status == "paused"
    assert source.score == 85  # the score refreshes, the decision does not
