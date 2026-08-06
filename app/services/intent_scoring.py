"""Two-stage intent scoring. TZ section 16.1.

Stage 1: quick_filter (cheap keyword/regex pass, no AI) discards most noise.
Stage 2: full_intent_analysis (AI) scores what survives stage 1.
"""
from __future__ import annotations

from typing import Any

# Baseline for authors who are NOT buyers. Kept as the floor for a geo whose own
# vocabulary is missing or thin. The renter-side terms were added after the first
# live run: a long-term rental chat produced 22 "signals" from people looking to
# rent ("#ищу жильё", "#сниму", "на год", "БЮДЖЕТ до 25.000₽" per month).
# Seller-side markers matter as much as renter-side ones, and cannot be left to
# the per-geo vocabulary: the AI regenerates it each time and dropped "продам"
# between two runs, after which "СОБСТВЕННИК! Срочно продам участок" sailed
# through stage 1 on the live feed.
NEGATIVE_KEYWORDS = [
    "продаю", "продам", "продаётся", "продается", "продаж",
    "собственник", "без посредников", "торг уместен",
    "сдаю", "сдам", "аренда от", "вакансия", "работа",
    "сниму", "ищу жильё", "ищу жилье", "сниме", "в аренду", "посуточно",
]

# Baseline purchase intent. quick_filter unions this with the geo's own
# intent_phrases so recall does not depend on what the AI happened to generate
# for a given city.
#
# Bare "покупк" and "купить" are deliberately absent: they match seller and
# advertising language just as well ("встречная покупка", "покупателю",
# "купить квартиру в ЖК Черноморский"), and on the live feed they were what let
# adverts and owner listings through.
BUY_INTENT_KEYWORDS = [
    "куплю", "хочу купить", "приобрет",
    # Bare stem, not "ищу квартир": people write "Ищу 2-комнатную квартиру", and
    # the compound never matched that -- the canonical buyer message was being
    # dropped at stage 1. Renters saying "ищу жильё" are caught by the negatives,
    # which win, and the city + property/financial clause carries the rest.
    "ищу",
    # Chat shorthand for a buyer request: "Запрос: квартира в Геленджике,
    # бюджет 5 млн". No verb at all, so nothing else here matches it.
    "запрос",
    # First-person deliberation. "рассматрива"/"планиру" carry the intent on
    # their own -- "рассматриваем покупку дома" does not contain the literal
    # "рассматрива покупк" -- and sellers do not write them about themselves.
    "присматрива", "рассматрива", "планиру",
    "переезжа", "подскажите район",
]


def quick_filter(message_text: str, geo_keywords: dict[str, Any]) -> bool:
    """Stage 1: fast pre-filter. Returns True if the message is worth AI scoring."""
    text = (message_text or "").lower()

    def _any(key: str) -> bool:
        return any(str(v).lower() in text for v in geo_keywords.get(key, []))

    city_mentioned = _any("city_variations")
    intent_signal = _any("intent_phrases") or any(p in text for p in BUY_INTENT_KEYWORDS)
    financial_signal = _any("financial_terms")
    property_signal = _any("property_terms")

    # TZ 16.1 accepts city AND (intent OR financial OR property), i.e. a property
    # word alone is enough. On the first live run that let a furniture shop advert
    # and a houseplant listing through: both name "Геленджикский" and contain the
    # stem "дома" (inside "домашняя"). Of 25 collected messages, 25 were noise.
    # Purchase intent is now required -- it is what the whole pipeline is looking
    # for, and TZ 35.4 expects this stage to drop >80% before any AI spend.
    passes = city_mentioned and intent_signal and (financial_signal or property_signal)
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


def content_fingerprint(text: str) -> str:
    """Stable fingerprint of a message body, for spotting reposted content.

    Agencies repost the same listing verbatim across chats and days, only the
    message id changing -- one advert reached the live signal queue five times.
    Whitespace, case and decoration are normalised so cosmetic edits still
    collapse onto the same fingerprint.
    """
    import hashlib
    import re

    normalized = re.sub(r"[^\w]+", " ", (text or "").lower(), flags=re.UNICODE).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
