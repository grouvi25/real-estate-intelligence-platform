"""Суб-поиск 5: каналы YouTube. ТЗ «Сигналы» 2.3.

search.list costs 100 quota units, so a run makes at most two searches and the
rate guard holds discovery to 5 000 units a day -- half the daily quota, the
other half stays with the collector. Channels under 500 subscribers are dropped
as the ТЗ asks; "uploaded in the last 90 days" is checked by the sandbox test,
which reads the uploads anyway.
"""
from __future__ import annotations

import structlog

from app.services.discovery.keyword_builder import take_queries
from app.services.discovery.searchers.base import Searcher, SearchContext
from app.services.discovery.types import YOUTUBE, KeywordMatrix, SourceCandidate

logger = structlog.get_logger()

SEARCH_COST = 100
MIN_SUBSCRIBERS = 500


class YouTubeSearcher(Searcher):
    platform = YOUTUBE
    title = "YouTube"

    async def search(self, kw: KeywordMatrix, ctx: SearchContext) -> list[SourceCandidate]:
        yt = ctx.clients.youtube()
        if yt is None:
            return []
        ids: dict[str, dict] = {}
        for query in await take_queries(ctx.geo_id, YOUTUBE, kw.queries_for(YOUTUBE)):
            if not await ctx.guard.spend(YOUTUBE, SEARCH_COST):
                break
            res = await yt._call("search", part="snippet", type="channel", regionCode="RU",
                                 relevanceLanguage="ru", maxResults=10, q=query)
            for item in (res or {}).get("items") or []:
                cid = (item.get("id") or {}).get("channelId")
                if cid:
                    ids.setdefault(cid, item.get("snippet") or {})
        if not ids or not await ctx.guard.spend(YOUTUBE, 1):
            return []
        stats = await yt._call("channels", part="statistics,snippet", id=",".join(list(ids)[:50]))
        out = []
        for ch in (stats or {}).get("items") or []:
            st = ch.get("statistics") or {}
            subs = int(st.get("subscriberCount") or 0)
            if subs < MIN_SUBSCRIBERS:
                continue
            sn = ch.get("snippet") or {}
            out.append(SourceCandidate(
                platform=YOUTUBE, external_id=ch["id"], name=sn.get("title") or ch["id"],
                url=f"https://www.youtube.com/channel/{ch['id']}", audience=subs,
                description=(sn.get("description") or "")[:500],
                meta={"video_count": int(st.get("videoCount") or 0)},
            ))
        return out
