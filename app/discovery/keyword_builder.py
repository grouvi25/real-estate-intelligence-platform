"""Keyword builder for a new geo. TZ section 15.1.

Uses AI to produce search queries + filter vocabularies (city variations, intent
phrases, financial/property terms, negatives) that feed Source Discovery and the
quick_filter stage of intent scoring.
"""
from __future__ import annotations

from typing import Any

_DEFAULT_KEYWORDS = {
    "search_queries": {"telegram": [], "vk_groups": []},
    "city_variations": [],
    "intent_phrases": [],
    "financial_terms": [],
    "property_terms": [],
    "negative_keywords": [],
}


async def generate_geo_keywords(city_data: dict[str, Any]) -> dict:
    """Generate the full keyword set for a geo. Returns parsed AI JSON (safe default)."""
    from app.prompts.geo_keywords import SYSTEM_PROMPT_GEO_KEYWORDS, USER_PROMPT_GEO_KEYWORDS
    from app.services.ai_service import AIService, safe_ai_parse

    ai = AIService()
    try:
        prompt = USER_PROMPT_GEO_KEYWORDS.format(
            city_name=city_data.get("city_name", ""),
            region=city_data.get("region", ""),
            market_type=city_data.get("market_type", "urban"),
            primary_segments=city_data.get("primary_segments", []),
        )
        res = await ai.complete(
            SYSTEM_PROMPT_GEO_KEYWORDS,
            prompt,
            "geo_keywords",
            agency_id=str(city_data.get("agency_id", "global")),
        )
        return safe_ai_parse(res, dict(_DEFAULT_KEYWORDS))
    finally:
        await ai.close()
