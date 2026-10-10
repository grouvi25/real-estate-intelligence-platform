"""Суб-поиск 2: группы ВКонтакте. ТЗ «Сигналы» 2.3.

groups.search with a service key answers error 15 ("user only") -- the ТЗ
suggests exactly that key, and it does not work. The collector already falls
back to newsfeed.search, which a service key may call: every post found names
its publisher, so the groups that keep writing about the city surface by
themselves. That path is reused here as is.
"""
from __future__ import annotations

from app.services.discovery.keyword_builder import take_queries
from app.services.discovery.searchers.base import Searcher, SearchContext
from app.services.discovery.types import VK, KeywordMatrix, SourceCandidate

# One query costs the search call plus the wall/board reads of what it finds.
CALLS_PER_QUERY = 10


class VKGroupSearcher(Searcher):
    platform = VK
    title = "ВКонтакте"

    async def search(self, kw: KeywordMatrix, ctx: SearchContext) -> list[SourceCandidate]:
        vk = ctx.clients.vk()
        if vk is None:
            return []
        queries = await take_queries(ctx.geo_id, VK, kw.queries_for(VK))
        if not queries or not await ctx.guard.spend(VK, CALLS_PER_QUERY * len(queries)):
            return []
        groups = await vk.search_groups(queries)
        return [
            SourceCandidate(
                platform=VK,
                external_id=str(g.get("username") or g.get("id")),
                name=g.get("name") or g.get("username") or "",
                url=g.get("url") or f"https://vk.com/{g.get('username')}",
                audience=int(g.get("members") or 0),
                description=g.get("description") or "",
                samples=list(g.get("samples") or []),
                meta={"vk_group_id": g.get("id")},
            )
            for g in groups if g.get("username") or g.get("id")
        ]
