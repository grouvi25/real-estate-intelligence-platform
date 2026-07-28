"""Two-stage intent scoring. TZ section 16.1.

Stage 1: quick_filter (cheap keyword/regex pass, no AI) discards most noise.
Stage 2: full_intent_analysis (AI) scores what survives stage 1.
"""
from __future__ import annotations

from typing import Any

# Baseline for authors who are NOT buyers (selling / renting out / jobs). Kept as
# the floor for a geo whose own vocabulary is missing or thin.
NEGATIVE_KEYWORDS = ["продаю", "сдаю", "сдам", "аренда от", "вакансия", "работа"]


def quick_filter(message_text: str, geo_keywords: dict[str, Any]) -> bool:
    """Stage 1: fast pre-filter. Returns True if the message is worth AI scoring."""
    text = (message_text or "").lower()

    def _any(key: str) -> bool:
        return any(str(v).lower() in text for v in geo_keywords.get(key, []))

    city_mentioned = _any("city_variations")
    intent_signal = _any("intent_phrases")
    financial_signal = _any("financial_terms")
    property_signal = _any("property_terms")

    passes = city_mentioned and (intent_signal or financial_signal or property_signal)
    # TZ 16.1 hardcodes the negative list and never reads the geo's own
    # negative_keywords, so the per-geo vocabulary the keyword builder generates
    # and stores was dead data. It cost real precision: the baseline has "продаю"
    # but not "продам", so "Продам дом в Геленджике" -- a seller -- passed stage 1
    # on the live geo and would have burned an AI call. Union the two.
    is_negative = any(p in text for p in NEGATIVE_KEYWORDS) or _any("negative_keywords")
    return passes and not is_negative


async def full_intent_analysis(message: dict[str, Any], geo_profile: dict[str, Any]) -> dict:
    """Stage 2: AI scoring. Returns the parsed AI JSON (with safe fallback)."""
    from app.prompts.intent_scoring import SYSTEM_PROMPT_INTENT_SCORING, USER_PROMPT_INTENT
    from app.services.ai_service import AIService, safe_ai_parse

    ai = AIService()
    try:
        prompt = USER_PROMPT_INTENT.format(
            geo_city=geo_profile.get("city_name", "Не указано"),
            source_name=message.get("source_name", "Unknown"),
            message_text=message.get("text", ""),
        )
        res = await ai.complete(
            SYSTEM_PROMPT_INTENT_SCORING,
            prompt,
            "intent_scoring",
            agency_id=str(geo_profile.get("agency_id", "global")),
        )
        return safe_ai_parse(res, {"intent_score": 0, "segment": "not_buyer"})
    finally:
        await ai.close()
