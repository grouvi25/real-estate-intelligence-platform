"""Keyword builder for a new geo. TZ section 15.1.

Uses AI to produce search queries + filter vocabularies (city variations, intent
phrases, financial/property terms, negatives) that feed Source Discovery and the
quick_filter stage of intent scoring.

The AI output is sanitised before it is stored, because two of these lists decide
whether the intake works at all and a smaller model does not reliably respect the
prompt. Observed on the live Геленджик geo: city_variations came back as
["краснодарский край", "краснодар", "сочи", "анапа", "туапсе", "арбат", ...] --
the region plus unrelated cities. quick_filter ANDs that list against the message
text, so a region entry lets everything through and a foreign-city entry turns
Sochi chatter into Геленджик signals. _sanitize() enforces the invariants in code
rather than hoping for prompt compliance.

Coastal settlements around a resort city (Кабардинка, Дивноморское, ...) are
deliberately not accepted here: they are separate markets and belong in their own
GeoLocation rows, which the multi-geo flow already supports (TZ 35.5).
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

_LIST_FIELDS = ("intent_phrases", "financial_terms", "property_terms", "negative_keywords")

# Enough to keep declensions and compound forms ("Геленджике", "Геленджик-город")
# while rejecting a different toponym that merely shares a first letter.
_CITY_PREFIX_LEN = 5

_QUERY_TEMPLATES = (
    "{city} недвижимость чат",
    "{city} купить квартиру",
    "{city} новостройки",
    "{city} барахолка",
    "{city} чат",
)


def _clean_list(values: Any) -> list[str]:
    """Strip, drop empties, de-duplicate case-insensitively, preserve order and case."""
    out: list[str] = []
    seen: set[str] = set()
    for v in values if isinstance(values, list) else []:
        s = str(v).strip()
        key = s.lower()
        if s and key not in seen:
            seen.add(key)
            out.append(s)
    return out


def _city_variations(raw: Any, city_name: str) -> list[str]:
    """Keep only forms of this city's own name, with the city itself guaranteed."""
    city = city_name.strip()
    if not city:
        return _clean_list(raw)

    lowered = city.lower()
    prefix = lowered[:_CITY_PREFIX_LEN]
    out = [city]
    for v in _clean_list(raw):
        key = v.lower()
        if key == lowered or len(key) < 3:
            continue
        # A real variation either extends the city stem ("Геленджике") or is a
        # truncation of it ("Гелендж"). Anything else is a different toponym.
        if key.startswith(prefix) or lowered.startswith(key):
            out.append(v)
    return out


def _search_queries(raw: Any, city_name: str) -> dict[str, list[str]]:
    """Drop queries that do not name the city; fall back to templates if none do."""
    city = city_name.strip()
    raw = raw if isinstance(raw, dict) else {}
    result: dict[str, list[str]] = {}
    for channel in ("telegram", "vk_groups"):
        queries = [q for q in _clean_list(raw.get(channel)) if city.lower() in q.lower()]
        if not queries and city:
            queries = [t.format(city=city) for t in _QUERY_TEMPLATES]
        result[channel] = queries
    return result


def _sanitize(parsed: Any, city_name: str) -> dict:
    """Coerce AI output into the shape the rest of the pipeline relies on."""
    parsed = parsed if isinstance(parsed, dict) else {}
    out = {
        "search_queries": _search_queries(parsed.get("search_queries"), city_name),
        "city_variations": _city_variations(parsed.get("city_variations"), city_name),
        **{f: _clean_list(parsed.get(f)) for f in _LIST_FIELDS},
    }
    # safe_ai_parse marks unusable AI responses; keep the flag visible to callers.
    if parsed.get("parse_error"):
        out["parse_error"] = True
    return out


async def generate_geo_keywords(city_data: dict[str, Any]) -> dict:
    """Generate the full keyword set for a geo. Returns sanitised AI JSON."""
    from app.prompts.geo_keywords import SYSTEM_PROMPT_GEO_KEYWORDS, USER_PROMPT_GEO_KEYWORDS
    from app.services.ai_service import AIService, safe_ai_parse

    city_name = str(city_data.get("city_name", ""))
    ai = AIService()
    try:
        prompt = USER_PROMPT_GEO_KEYWORDS.format(
            city_name=city_name,
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
        return _sanitize(safe_ai_parse(res, dict(_DEFAULT_KEYWORDS)), city_name)
    finally:
        await ai.close()
