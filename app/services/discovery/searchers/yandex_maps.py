"""Суб-поиск 7: агентства недвижимости в Яндекс.Картах. ТЗ «Сигналы» 2.3.

Needs a key for the organisation search API ("API Поиска по организациям",
YANDEX_PLACES_API_KEY): the JS-Maps and geocoder keys REIP already has answer
"Invalid api key" there (checked 11.10.2026). Without it the searcher is idle.

What it gives is not a source -- that API returns no posts and no reviews, so the
ТЗ's "poll new reviews daily" has nothing to poll. It gives the agency's
competitors: their names go to the signal category filter (апгрейд B), where a
message naming a competitor is filed as «Конкуренты».
"""
from __future__ import annotations

import structlog

from app.config import config
from app.services.discovery.searchers.base import NEEDS_KEY, Searcher, SearchContext
from app.services.discovery.types import YANDEX_MAPS, KeywordMatrix, SourceCandidate

logger = structlog.get_logger()

API = "https://search-maps.yandex.ru/v1/"


def parse_organisations(body: dict) -> list[str]:
    names = []
    for feature in (body or {}).get("features") or []:
        meta = (feature.get("properties") or {}).get("CompanyMetaData") or {}
        name = (meta.get("name") or "").strip()
        if name:
            names.append(name)
    return names


class YandexMapsSearcher(Searcher):
    platform = YANDEX_MAPS
    title = "Яндекс.Карты (конкуренты)"
    why_unavailable = "нужен ключ «API Поиска по организациям» (YANDEX_PLACES_API_KEY)"

    def state(self) -> str:
        return super().state() if config.yandex_places_api_key else NEEDS_KEY

    async def search(self, kw: KeywordMatrix, ctx: SearchContext) -> list[SourceCandidate]:
        if not config.yandex_places_api_key or not await ctx.guard.spend(YANDEX_MAPS):
            return []
        http = await ctx.clients.http()
        try:
            res = await http.get(API, params={
                "apikey": config.yandex_places_api_key, "lang": "ru_RU", "type": "biz",
                "results": 50, "text": f"агентство недвижимости {kw.city}"})
            body = res.json() if res.status_code < 400 else {}
        except Exception as e:  # noqa: BLE001
            logger.warning("Yandex Places unavailable", error=str(e)[:120])
            return []
        ctx.competitors_found.extend(parse_organisations(body))
        return []
