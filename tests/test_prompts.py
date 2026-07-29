"""Tests that all AI prompts load, demand JSON, and format correctly."""
import importlib

import pytest

SYSTEM_PROMPTS = {
    "intent_scoring": "SYSTEM_PROMPT_INTENT_SCORING",
    "buyer_profile": "SYSTEM_PROMPT_BUYER_PROFILE",
    "object_analysis": "SYSTEM_PROMPT_OBJECT_ANALYSIS",
    "pitch_generator": "SYSTEM_PROMPT_MATCHING_PITCH",
    "reply_generator": "SYSTEM_PROMPT_REPLY",
    "source_evaluation": "SYSTEM_PROMPT_TELEGRAM_SOURCE_EVAL",
    "daily_report": "SYSTEM_PROMPT_DAILY_REPORT",
    "market_analysis": "SYSTEM_PROMPT_MARKET_EVENT",
    "listing_generator": "SYSTEM_PROMPT_LISTING",
    "geo_keywords": "SYSTEM_PROMPT_GEO_KEYWORDS",
    "qualification": "SYSTEM_PROMPT_QUALIFICATION",
}


@pytest.mark.parametrize("module,const", SYSTEM_PROMPTS.items())
def test_system_prompt_present_and_requires_json(module, const):
    mod = importlib.import_module(f"app.prompts.{module}")
    value = getattr(mod, const)
    assert isinstance(value, str) and value.strip()
    assert "JSON" in value


def test_intent_user_prompt_formats():
    from app.prompts.intent_scoring import USER_PROMPT_INTENT

    s = USER_PROMPT_INTENT.format(geo_city="Геленджик", source_name="Чат", message_text="ищу")
    assert "Геленджик" in s and "Чат" in s


def test_geo_keywords_user_prompt_formats():
    from app.prompts.geo_keywords import USER_PROMPT_GEO_KEYWORDS

    s = USER_PROMPT_GEO_KEYWORDS.format(
        city_name="Геленджик", region="Краснодарский край", market_type="resort",
        primary_segments=["family", "investor"],
    )
    assert "resort" in s


def test_geo_keywords_prompt_pins_city_level_output():
    """quick_filter ANDs city_variations against the text, so region-level output
    silently zeroes out the whole signal intake. The prompt must say so."""
    from app.prompts.geo_keywords import SYSTEM_PROMPT_GEO_KEYWORDS, USER_PROMPT_GEO_KEYWORDS

    assert "НИКОГДА не включай сюда название региона" in SYSTEM_PROMPT_GEO_KEYWORDS
    assert "вхождение подстроки" in SYSTEM_PROMPT_GEO_KEYWORDS
    assert "НЕ включай его в city_variations" in USER_PROMPT_GEO_KEYWORDS


def test_pitch_user_prompt_formats():
    from app.prompts.pitch_generator import USER_PROMPT_PITCH

    s = USER_PROMPT_PITCH.format(
        segment="family", purchase_goal="own", budget_min=5, budget_max=8,
        mortgage_type="standard", timeline="3 мес", family="2+1", priorities="море",
        deal_breakers="", emotional_profile="", property_type="квартира", address="ул. X",
        price=7, area=60, rooms=2, floor=3, floors_total=9, readiness_status="ready",
        strengths="вид", weaknesses="этаж", amenities="школа",
    )
    assert "family" in s and "квартира" in s


def test_intent_prompt_scores_the_author_not_the_topic():
    """TZ 27.1 said "определить признаки намерения купить" without saying whose.
    On the live feed a Спортмастер opening advert -- which mentions local
    development and property -- came back as intent 60, segment "investor". A
    manager would have been handed an advert as a warm lead."""
    from app.prompts.intent_scoring import SYSTEM_PROMPT_INTENT_SCORING as P

    assert "намерение автора, а не тема текста" in P
    assert "реклама" in P and "анонсы" in P
    assert "не от первого лица" in P


def test_intent_prompt_separates_renting_from_buying():
    """A concrete "сниму квартиру ... семья" scored 80 as a family buyer until
    the prompt said outright that renting is not a purchase."""
    from app.prompts.intent_scoring import SYSTEM_PROMPT_INTENT_SCORING as P

    assert "СНЯТЬ жильё — это НЕ покупка" in P
    assert "покупка в собственность" in P
