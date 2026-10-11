"""Суб-поиск 3: ленты новостей через Google News RSS. ТЗ «Сигналы» 2.3.

Google News answers a query with articles, each naming its publisher
(<source url="https://site">Name</source>). Publishers that write about the city
more than once become candidates; their own feed is then looked up on their site
(robots.txt honoured). A news feed brings market news rather than buyers, and the
evaluation prompt scores it accordingly (40-50: sandbox, the owner decides).

Not done, and why: Yandex News RSS search is shut down (the host does not
answer), avito.ru/rss and cian.ru/rss answer 404 -- checked 11.10.2026.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlsplit
from xml.etree import ElementTree

import structlog

from app.services.discovery.keyword_builder import take_queries
from app.services.discovery.searchers.base import Searcher, SearchContext
from app.services.discovery.searchers.feeds import discover_feed
from app.services.discovery.types import RSS, KeywordMatrix, SourceCandidate

logger = structlog.get_logger()

GOOGLE_NEWS = "https://news.google.com/rss/search?q={q}&hl=ru&gl=RU&ceid=RU:ru"
MIN_ARTICLES = 2
FEEDS_PER_RUN = 5
# Aggregators and the big federal outlets: their feed is the whole country.
SKIP_DOMAINS = ("google.", "yandex.", "dzen.ru", "rambler.ru", "mail.ru", "ria.ru", "tass.ru",
                "rbc.ru", "kommersant.ru", "lenta.ru", "gazeta.ru", "iz.ru", "vedomosti.ru")


def parse_publishers(xml: str) -> list[dict]:
    """[{domain, name, at}] for every article of a Google News feed."""
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return []
    out = []
    for item in root.iter("item"):
        source = item.find("source")
        if source is None or not source.get("url"):
            continue
        domain = urlsplit(source.get("url")).netloc.lower().removeprefix("www.")
        at = None
        raw = (item.findtext("pubDate") or "").strip()
        if raw:
            try:
                at = parsedate_to_datetime(raw)
            except (TypeError, ValueError):
                at = None
        out.append({"domain": domain, "name": (source.text or domain).strip(), "at": at,
                    "title": (item.findtext("title") or "").strip()})
    return out


class RSSDiscoverer(Searcher):
    platform = RSS
    title = "Новостные ленты (Google News)"

    async def search(self, kw: KeywordMatrix, ctx: SearchContext) -> list[SourceCandidate]:
        http = await ctx.clients.http()
        articles: list[dict] = []
        for query in await take_queries(ctx.geo_id, RSS, kw.queries_for(RSS)):
            if not await ctx.guard.spend(RSS):
                break
            try:
                res = await http.get(GOOGLE_NEWS.format(q=quote(query)))
                if res.status_code < 400:
                    articles += parse_publishers(res.text)
            except Exception as e:  # noqa: BLE001
                logger.warning("Google News unavailable", error=str(e)[:120])
                break

        counts = Counter(a["domain"] for a in articles)
        latest: dict[str, datetime] = {}
        names: dict[str, str] = {}
        titles: dict[str, list[str]] = {}
        for a in articles:
            names.setdefault(a["domain"], a["name"])
            titles.setdefault(a["domain"], []).append(a["title"])
            if a["at"] and (a["domain"] not in latest or a["at"] > latest[a["domain"]]):
                latest[a["domain"]] = a["at"]

        out: list[SourceCandidate] = []
        for domain, n in counts.most_common():
            if len(out) >= FEEDS_PER_RUN or n < MIN_ARTICLES:
                break
            if any(skip in domain for skip in SKIP_DOMAINS):
                continue
            feed = await discover_feed(http, domain)
            if not feed:
                continue
            out.append(SourceCandidate(
                platform=RSS, external_id=feed, name=names.get(domain, domain), url=feed,
                last_post_at=latest.get(domain),
                samples=titles.get(domain, [])[:5],
                meta={"domain": domain, "articles_about_city": n,
                      "seen_at": datetime.now(timezone.utc).isoformat()},
            ))
        return out
