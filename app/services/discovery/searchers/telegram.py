"""Суб-поиск 1: Telegram через MTProto (contacts.Search). ТЗ «Сигналы» 2.3.

Only the account Telethon collects with, only under the shared lock, at most
QUERIES_PER_RUN queries a run with a ≥5 s pause between them, and every request
is paid for in the rate guard first. Posts are not read here -- the sandbox test
reads them once, for the candidates that survive ranking and de-duplication.

tgstat.ru / telemetr.io from the ТЗ are in tg_catalog.py (a stub, see there).
"""
from __future__ import annotations

import asyncio

import structlog

from app.services.discovery.keyword_builder import take_queries
from app.services.discovery.searchers.base import Searcher, SearchContext
from app.services.discovery.types import TELEGRAM, KeywordMatrix, SourceCandidate

logger = structlog.get_logger()

PAUSE_SECONDS = 5
RESULTS_PER_QUERY = 10


class TelegramSearcher(Searcher):
    platform = TELEGRAM
    title = "Telegram"

    async def search(self, kw: KeywordMatrix, ctx: SearchContext) -> list[SourceCandidate]:
        client = await ctx.clients.telegram()
        if client is None:
            return []
        from telethon.tl.functions.contacts import SearchRequest  # noqa: PLC0415

        found: dict[str, SourceCandidate] = {}
        queries = await take_queries(ctx.geo_id, TELEGRAM, kw.queries_for(TELEGRAM))
        for i, query in enumerate(queries):
            if not await ctx.guard.spend(TELEGRAM):
                break
            if i:
                await asyncio.sleep(PAUSE_SECONDS)
            try:
                res = await client(SearchRequest(q=query, limit=RESULTS_PER_QUERY))
            except Exception as e:  # noqa: BLE001 - flood wait, network
                logger.warning("Telegram search failed", query=query, error=str(e)[:120])
                break
            for chat in getattr(res, "chats", []) or []:
                username = getattr(chat, "username", None)
                if not username:
                    continue  # a chat without a handle cannot be collected
                found[username.lower()] = SourceCandidate(
                    platform=TELEGRAM,
                    external_id=username,
                    name=getattr(chat, "title", None) or username,
                    url=f"https://t.me/{username}",
                    audience=getattr(chat, "participants_count", 0) or 0,
                    meta={"broadcast": bool(getattr(chat, "broadcast", False)),
                          "query": query},
                )
        return list(found.values())
