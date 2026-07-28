"""Tests for two-stage intent scoring (quick_filter + AI stage)."""
import pytest

from app.services.intent_scoring import full_intent_analysis, quick_filter

GEO = {
    "city_variations": ["геленджик", "гдж"],
    "intent_phrases": ["ищу", "хочу купить", "присматриваю"],
    "financial_terms": ["ипотека", "бюджет", "млн"],
    "property_terms": ["квартира", "студия", "дом"],
}


def test_quick_filter_passes_real_buyer():
    assert quick_filter("Ищу квартиру в Геленджике до 8 млн", GEO) is True


def test_quick_filter_requires_city():
    assert quick_filter("ищу квартиру до 8 млн", GEO) is False


def test_quick_filter_rejects_seller():
    assert quick_filter("Продаю квартиру в Геленджике, звоните", GEO) is False


def test_quick_filter_requires_intent_or_financial_or_property():
    assert quick_filter("Геленджик хороший город", GEO) is False


def test_quick_filter_empty():
    assert quick_filter("", GEO) is False


def test_quick_filter_uses_geo_negative_keywords():
    """The per-geo vocabulary must apply, not just the module baseline.

    The baseline has "продаю" but not "продам", so this seller slipped through on
    the live Геленджик geo even though its generated negative_keywords listed it.
    """
    geo = {**GEO, "negative_keywords": ["продам", "посуточно"]}

    assert quick_filter("Продам дом в Геленджике, срочно", GEO) is True  # baseline misses it
    assert quick_filter("Продам дом в Геленджике, срочно", geo) is False
    assert quick_filter("Сдам квартиру в Геленджике посуточно", geo) is False
    # A real buyer is unaffected.
    assert quick_filter("Ищу квартиру в Геленджике до 8 млн", geo) is True


@pytest.mark.asyncio
async def test_full_intent_analysis_parses_ai(monkeypatch):
    from app.services.ai_service import AIService

    async def fake_complete(self, system, user, module, agency_id="global"):
        assert module == "intent_scoring"
        assert "Геленджик" in user
        return '{"intent_score": 85, "segment": "family", "urgency": "hot"}'

    monkeypatch.setattr(AIService, "complete", fake_complete)
    result = await full_intent_analysis(
        {"text": "ищу квартиру", "source_name": "Чат"}, {"city_name": "Геленджик"}
    )
    assert result["intent_score"] == 85
    assert result["segment"] == "family"


@pytest.mark.asyncio
async def test_full_intent_analysis_bad_json_fallbacks(monkeypatch):
    from app.services.ai_service import AIService

    async def fake_complete(self, system, user, module, agency_id="global"):
        return "the model rambled without json"

    monkeypatch.setattr(AIService, "complete", fake_complete)
    result = await full_intent_analysis({"text": "x"}, {"city_name": "Сочи"})
    assert result["intent_score"] == 0
    assert result["segment"] == "not_buyer"
    assert result["parse_error"] is True
