"""Суб-поиск 9: региональные форумы из discovery_forum_seeds. ТЗ «Сигналы» 2.3.

The ТЗ searches seeded forums through Google Site Search, which Google closed;
its successor (Custom Search JSON API) is not open to new customers. Instead the
seeded forum's own feed is found on the site (robots.txt honoured) and offered as
a candidate; the sandbox test then reads it like any other feed.
"""
from __future__ import annotations

from sqlalchemy import func, select

from app.services.discovery.searchers.base import Searcher, SearchContext
from app.services.discovery.searchers.feeds import discover_feed
from app.services.discovery.types import FORUM, KeywordMatrix, SourceCandidate

SEEDS_PER_RUN = 5


class ForumDiscoverer(Searcher):
    platform = FORUM
    title = "Форумы (список администратора)"

    async def search(self, kw: KeywordMatrix, ctx: SearchContext) -> list[SourceCandidate]:
        if ctx.session is None:
            return []
        from app.models.discovery import DiscoveryForumSeed  # noqa: PLC0415

        seeds = (await ctx.session.execute(select(DiscoveryForumSeed).where(
            DiscoveryForumSeed.active.is_(True),
            func.lower(DiscoveryForumSeed.city).in_([v.lower() for v in kw.city_variations]),
        ))).scalars().all()
        http = await ctx.clients.http()
        out = []
        for seed in seeds[:SEEDS_PER_RUN]:
            if not await ctx.guard.spend(FORUM):
                break
            feed = await discover_feed(http, seed.domain)
            if feed:
                out.append(SourceCandidate(
                    platform=FORUM, external_id=feed, name=seed.description or seed.domain,
                    url=feed, meta={"domain": seed.domain, "seed_id": str(seed.id)}))
        return out
