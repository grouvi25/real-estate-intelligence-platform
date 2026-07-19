"""Two-stage intent scoring. TZ section 16.1.

Stage 1: quick_filter (cheap keyword/regex pass, no AI) discards most noise.
Stage 2: full_intent_analysis (AI) scores what survives stage 1.
"""
from __future__ import annotations

from typing import Any

# Messages that indicate the author is NOT a buyer (selling / renting out / jobs).
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
    is_negative = any(p in text for p in NEGATIVE_KEYWORDS)
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
