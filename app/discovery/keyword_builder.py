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

# Telegram's public search matches on chat titles, so each template is a
# different way a local chat might name itself. The first live run over
# Геленджик surfaced 18 candidates from five queries and only one of them was
# about buying property -- narrow phrasing was part of why.
#
# «объявления», «барахолка» and «квартиры» used to be in here, and they worked
# exactly as asked: Discovery found eight classified-ad boards, the scorer
# correctly parked them in the sandbox, and over a week the collector read 2169
# messages off them and produced two signals. Sampling 400 of those messages
# found purchase intent in four, and the closest to a buyer was looking to rent.
# An ad board is where sellers post; a buyer asks about districts and schools
# before they ever write "куплю". So the search asks for conversation now. A
# board that is genuinely good can still be added by hand.
_QUERY_TEMPLATES = (
    "{city} недвижимость",
    "{city} недвижимость чат",
    "{city} купить квартиру",
    "{city} куплю квартиру",
    "{city} новостройки",
    "{city} ЖК",
    "{city} ипотека",
    "{city} чат",
    "{city} чат жителей",
    "{city} форум",
    "{city} переезд",
    "переезд в {city}",
    "Недвижимость {city}",
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
        # Keep whatever the AI produced that actually names the city, then top up
        # with the templates. Using templates only as a fallback meant that one
        # usable AI query crowded out eleven good ones -- and on the live geo the
        # AI's queries were region-level and dropped entirely, so the search ran
        # on the fallback alone.
        queries = [q for q in _clean_list(raw.get(channel)) if city.lower() in q.lower()]
        if city:
            seen = {q.lower() for q in queries}
            for template in _QUERY_TEMPLATES:
                candidate = template.format(city=city)
                if candidate.lower() not in seen:
                    queries.append(candidate)
                    seen.add(candidate.lower())
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


_MERGED_LISTS = ("city_variations", "intent_phrases", "financial_terms", "property_terms")


def merge_keywords(old: Any, fresh: Any) -> tuple[dict, dict[str, list[str]]]:
    """Old vocabulary plus whatever the fresh one adds; returns (merged, added).

    Regenerating used to replace the lists, and the AI answers shorter every
    time: on Геленджик the city forms went 14 -> 3 and intent phrases 23 -> 5,
    which costs signals with no error anywhere. Merging keeps everything that
    already matched. A new negative keyword that occurs inside a kept phrase
    would silently block that phrase, so such negatives are dropped.
    """
    old = old if isinstance(old, dict) else {}
    fresh = fresh if isinstance(fresh, dict) else {}
    merged = dict(old)
    added: dict[str, list[str]] = {}
    for field in (*_MERGED_LISTS, "negative_keywords"):
        before = _clean_list(old.get(field))
        known = {v.lower() for v in before}
        new = [v for v in _clean_list(fresh.get(field)) if v.lower() not in known]
        if field == "negative_keywords":
            positives = [p.lower() for f in _MERGED_LISTS
                         for p in _clean_list(old.get(f)) + _clean_list(fresh.get(f))]
            new = [v for v in new if not any(v.lower() in p for p in positives)]
        merged[field] = before + new
        if new:
            added[field] = new
    queries = dict(old.get("search_queries") or {})
    for channel, values in (fresh.get("search_queries") or {}).items():
        before = _clean_list(queries.get(channel))
        known = {v.lower() for v in before}
        new = [v for v in _clean_list(values) if v.lower() not in known]
        queries[channel] = before + new
        if new:
            added[f"search_queries.{channel}"] = new
    merged["search_queries"] = queries
    return merged, added


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
