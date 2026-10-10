"""KeywordBuilder: what to search for, per platform. ТЗ «Сигналы» 2.2.

The matrix is built from the city's vocabulary the AI already produced when the
city was added (geo_locations.keywords) plus the query templates the old weekly
discovery used, instead of the hard-coded alias list in the ТЗ: a list in code
only knows the cities somebody typed into it.

Rental phrasing from the ТЗ («снять квартиру {city}») is left out on purpose:
REIP looks for buyers, and rental chats are exactly what the previous ТЗ asked to
filter out.

A run takes only a few queries per platform (QUERIES_PER_RUN), moving through the
list across runs with a cursor in Redis: hourly runs then cover the whole list
during the day without burning the hourly Telegram budget in one go.
"""
from __future__ import annotations

from typing import Optional

import structlog

from app.services.discovery.types import (
    FORUM,
    RSS,
    TELEGRAM,
    VK,
    YOUTUBE,
    KeywordMatrix,
)

logger = structlog.get_logger()

NICHE_TAGS = ["недвижимость", "риелтор", "риэлтор", "ипотека", "новостройка",
              "вторичка", "квартира", "дом", "участок", "переезд", "жк"]

# Phrases a buyer-oriented feed or channel would be found by.
_YOUTUBE_TEMPLATES = ("{city} недвижимость", "переезд в {city}", "{city} купить квартиру",
                      "{city} новостройки обзор", "жизнь в {city}")
_NEWS_TEMPLATES = ("недвижимость {city}", "новостройки {city}", "цены на жильё {city}",
                   "ипотека {city}")

QUERIES_PER_RUN = {TELEGRAM: 4, VK: 4, YOUTUBE: 2, RSS: 3}
CURSOR_KEY = "discovery:cursor:{geo}:{platform}"


def _unique(items) -> list[str]:
    seen: set[str] = set()
    out = []
    for item in items:
        text = (item or "").strip()
        if text and text.lower() not in seen:
            seen.add(text.lower())
            out.append(text)
    return out


def build_matrix(city: str, keywords: Optional[dict], competitor_names: list[str]) -> KeywordMatrix:
    from app.discovery.keyword_builder import _QUERY_TEMPLATES  # noqa: PLC0415

    keywords = keywords or {}
    search = keywords.get("search_queries") or {}
    templates = [t.format(city=city) for t in _QUERY_TEMPLATES]
    intent = _unique([p for p in (keywords.get("intent_phrases") or []) if city.lower() in p.lower()]
                     + templates)
    variations = _unique([city] + list(keywords.get("city_variations") or []))
    return KeywordMatrix(
        city=city,
        city_variations=variations,
        intent_queries=intent,
        niche_tags=list(NICHE_TAGS),
        competitor_names=_unique(competitor_names),
        platform_queries={
            TELEGRAM: _unique(list(search.get("telegram") or []) + templates),
            VK: _unique(list(search.get("vk_groups") or []) + templates),
            YOUTUBE: _unique(t.format(city=city) for t in _YOUTUBE_TEMPLATES),
            RSS: _unique(t.format(city=city) for t in _NEWS_TEMPLATES),
            FORUM: variations,
        },
    )


async def take_queries(geo_id, platform: str, queries: list[str], n: Optional[int] = None) -> list[str]:
    """The next ``n`` queries of the list, continuing where the last run stopped."""
    n = n or QUERIES_PER_RUN.get(platform, 3)
    if len(queries) <= n:
        return list(queries)
    from app.services.discovery.rate_limit_guard import redis_client  # noqa: PLC0415

    start = 0
    client = None
    try:
        client = redis_client()
        key = CURSOR_KEY.format(geo=geo_id, platform=platform)
        start = int(await client.incrby(key, n)) - n
        await client.expire(key, 30 * 24 * 3600)
    except Exception as e:  # noqa: BLE001 - без Redis просто с начала списка
        logger.warning("Discovery cursor unavailable", error=str(e)[:120])
    finally:
        if client is not None:
            await client.aclose()
    start %= len(queries)
    return [queries[(start + i) % len(queries)] for i in range(n)]


class KeywordBuilder:
    """ТЗ-shaped wrapper: one city of one agency."""

    def __init__(self, geo, competitor_names: Optional[list[str]] = None):
        self.geo = geo
        self.competitor_names = competitor_names or []

    async def refresh(self) -> KeywordMatrix:
        return build_matrix(self.geo.city_name, self.geo.keywords, self.competitor_names)
