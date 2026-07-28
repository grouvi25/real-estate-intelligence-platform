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


def test_sanitize_drops_region_and_foreign_cities():
    """Verbatim AI output from the live Геленджик geo (gpt-4o-mini)."""
    from app.discovery.keyword_builder import _sanitize

    kw = _sanitize(
        {
            "city_variations": [
                "краснодарский край", "краснодар", "краснодаре", "краснодарский",
                "сочи", "анапа", "геленджик", "туапсе", "арбат", "северская",
            ],
            "search_queries": {"telegram": ["недвижимость Краснодарский край"], "vk_groups": []},
        },
        "Геленджик",
    )
    # The AI's own "геленджик" collapses into the guaranteed city entry.
    assert kw["city_variations"] == ["Геленджик"]


def test_sanitize_keeps_declensions_and_truncations():
    from app.discovery.keyword_builder import _sanitize

    kw = _sanitize(
        {"city_variations": ["Геленджике", "Геленджика", "Гелендж", "Сочи"]}, "Геленджик"
    )
    assert "Геленджике" in kw["city_variations"]
    assert "Геленджика" in kw["city_variations"]
    assert "Гелендж" in kw["city_variations"]
    assert "Сочи" not in kw["city_variations"]


def test_sanitize_always_includes_the_city():
    """quick_filter ANDs on this list, so an empty/omitted city means zero signals."""
    from app.discovery.keyword_builder import _sanitize

    assert _sanitize({"city_variations": []}, "Геленджик")["city_variations"] == ["Геленджик"]
    assert _sanitize({}, "Геленджик")["city_variations"] == ["Геленджик"]


def test_sanitize_replaces_queries_that_omit_the_city():
    from app.discovery.keyword_builder import _sanitize

    kw = _sanitize(
        {"search_queries": {"telegram": ["недвижимость Краснодарский край"], "vk_groups": []}},
        "Геленджик",
    )
    assert kw["search_queries"]["telegram"]
    assert all("геленджик" in q.lower() for q in kw["search_queries"]["telegram"])
    assert all("геленджик" in q.lower() for q in kw["search_queries"]["vk_groups"])


def test_sanitize_keeps_queries_that_name_the_city():
    from app.discovery.keyword_builder import _sanitize

    kw = _sanitize(
        {"search_queries": {"telegram": ["Геленджик недвижимость чат", "Сочи чат"]}},
        "Геленджик",
    )
    assert kw["search_queries"]["telegram"] == ["Геленджик недвижимость чат"]


def test_sanitize_output_passes_quick_filter():
    """End-to-end guard: sanitised vocabularies must accept a real buyer message."""
    from app.discovery.keyword_builder import _sanitize
    from app.services.intent_scoring import quick_filter

    kw = _sanitize(
        {
            "city_variations": ["краснодарский край", "сочи", "геленджик"],
            "intent_phrases": ["ищу квартиру", "куплю"],
            "property_terms": ["квартир", "дом"],
            "financial_terms": ["ипотек"],
        },
        "Геленджик",
    )
    assert quick_filter("Ищу квартиру в Геленджике до 8 млн, рассматриваем ипотеку", kw) is True
    assert quick_filter("Ищу квартиру в Сочи до 8 млн", kw) is False


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
