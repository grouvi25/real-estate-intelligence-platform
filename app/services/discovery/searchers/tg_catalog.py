"""Суб-поиск 6: каталог Telegram-каналов о недвижимости (telemetr.io). ТЗ «Сигналы» 2.3.

telemetr.io keeps an open category "Недвижимость, Россия" -- ten pages of a
hundred channels, allowed by its robots.txt. A run reads up to PAGES_PER_RUN of
them (moving through the pages run by run) and keeps the channels whose title
names the city. For a small city that is often none: the catalogue is the
country's top, and that is the honest answer.

tgstat.ru from the ТЗ is not used: its category page is a 404, and its channel
search ignores the query for an anonymous visitor (returns the country-wide top).
"""
from __future__ import annotations

import asyncio
import html
import re

import structlog

from app.services.discovery.clients import robots_allows
from app.services.discovery.keyword_builder import take_queries
from app.services.discovery.searchers.base import Searcher, SearchContext
from app.services.discovery.types import TG_CATALOG, KeywordMatrix, SourceCandidate

logger = structlog.get_logger()

CATALOG = "https://telemetr.io/ru/catalog/russia/real-estate"
PAGES = 10
PAGES_PER_RUN = 2
PAUSE_SECONDS = 3
_ENTRY = re.compile(
    r'class="channel-name__title"\s+href="/ru/channels/(\d+)-([A-Za-z0-9_]+)"[^>]*>([^<]+)</a>'
    r'(?:(?!channel-name__title).){0,3000}?channels-table-cursor-pointer">([\d\s ]+)<',
    re.DOTALL)


def parse_catalog(page: str) -> list[dict]:
    out = []
    for tg_id, handle, title, subs in _ENTRY.findall(page):
        out.append({"id": tg_id, "username": handle, "title": html.unescape(title).strip(),
                    "subscribers": int(re.sub(r"\D", "", subs) or 0)})
    return out


def names_city(title: str, variations: list[str]) -> bool:
    low = title.lower().replace("ё", "е")
    # a five-letter stem catches «Геленджике», «Краснодарский»
    return any(v.lower().replace("ё", "е")[:max(5, len(v) - 2)] in low for v in variations if v)


class TelegramCatalogSearcher(Searcher):
    platform = TG_CATALOG
    title = "Каталог Telegram (telemetr.io)"

    async def search(self, kw: KeywordMatrix, ctx: SearchContext) -> list[SourceCandidate]:
        http = await ctx.clients.http()
        pages = await take_queries(ctx.geo_id, TG_CATALOG, [str(p) for p in range(1, PAGES + 1)],
                                   PAGES_PER_RUN)
        out: list[SourceCandidate] = []
        for i, page in enumerate(pages):
            url = CATALOG if page == "1" else f"{CATALOG}?page={page}"
            if not await robots_allows(http, url) or not await ctx.guard.spend(TG_CATALOG):
                break
            if i:
                await asyncio.sleep(PAUSE_SECONDS)
            try:
                res = await http.get(url)
                entries = parse_catalog(res.text) if res.status_code < 400 else []
            except Exception as e:  # noqa: BLE001
                logger.warning("telemetr.io unavailable", error=str(e)[:120])
                break
            for e in entries:
                if names_city(e["title"], kw.city_variations):
                    out.append(SourceCandidate(
                        platform=TG_CATALOG, external_id=e["username"], name=e["title"],
                        url=f"https://t.me/{e['username']}", audience=e["subscribers"],
                        meta={"catalog": "telemetr.io", "telegram_id": e["id"]}))
        return out
