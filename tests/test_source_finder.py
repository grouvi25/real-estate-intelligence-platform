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
