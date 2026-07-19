"""Tests for geo keyword builder + the keyword-generation task."""
import os
import uuid

import pytest


@pytest.mark.asyncio
async def test_generate_geo_keywords_parses(monkeypatch):
    from app.discovery.keyword_builder import generate_geo_keywords
    from app.services.ai_service import AIService

    async def fake_complete(self, system, user, module, agency_id="global"):
        assert module == "geo_keywords"
        return (
            '{"search_queries":{"telegram":["куплю квартиру геленджик"],"vk_groups":[]},'
            '"city_variations":["Геленджик","гдж"],"intent_phrases":["ищу"],'
            '"financial_terms":["ипотека"],"property_terms":["квартира"],'
            '"negative_keywords":["продаю"]}'
        )

    monkeypatch.setattr(AIService, "complete", fake_complete)
    kw = await generate_geo_keywords(
        {"city_name": "Геленджик", "region": "КК", "market_type": "resort", "primary_segments": ["family"]}
    )
    assert "Геленджик" in kw["city_variations"]
    assert kw["search_queries"]["telegram"]


@pytest.mark.asyncio
async def test_generate_geo_keywords_bad_json_default(monkeypatch):
    from app.discovery.keyword_builder import generate_geo_keywords
    from app.services.ai_service import AIService

    async def fake_complete(self, system, user, module, agency_id="global"):
        return "no json here"

    monkeypatch.setattr(AIService, "complete", fake_complete)
    kw = await generate_geo_keywords({"city_name": "X"})
    assert kw["parse_error"] is True
    assert "search_queries" in kw


@pytest.mark.skipif(os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL")
@pytest.mark.asyncio
async def test_geo_task_persists_keywords(monkeypatch):
    from app.database import async_session, run_migrations
    from app.models.agency import Agency
    from app.models.geo_location import GeoLocation
    from app.services.ai_service import AIService
    from worker.tasks.geo_tasks import _generate_keywords_for_geo

    async def fake_complete(self, system, user, module, agency_id="global"):
        return '{"city_variations":["Геленджик"],"intent_phrases":["ищу"]}'

    monkeypatch.setattr(AIService, "complete", fake_complete)
    await run_migrations()
    async with async_session() as s:
        agency = Agency(name="KW Agency", base_city="Геленджик")
        s.add(agency)
        await s.flush()
        geo = GeoLocation(agency_id=agency.id, city_name=f"Геленджик-{uuid.uuid4().hex[:6]}", geo_type="sales")
        s.add(geo)
        await s.commit()
        geo_id = str(geo.id)

    assert await _generate_keywords_for_geo(geo_id, {"city_name": "Геленджик"}) is True

    async with async_session() as s:
        geo = await s.get(GeoLocation, geo_id)
        assert "Геленджик" in geo.keywords["city_variations"]
