"""RSS/Atom collector. TZ section 3 manifest.

The schema allowed sources of type 'rss' and 'website' from the first migration
and nothing ever read one, so adding a feed on the Источники screen produced a
row that sat there for ever.

Feeds are where regional news and forum digests end up — «переезжаем в
Геленджик, посоветуйте район» in a forum thread reaches us here rather than
through a chat. The parsing is deliberately small: an RSS item is a title, a
link, a date and a summary, and every feed carries those under one of two
spellings (RSS <item> or Atom <entry>).

No credential to gate on, so the guard is the source list: nothing runs until an
agency adds a feed.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional
from xml.etree import ElementTree

import structlog

from app.services.intent_scoring import quick_filter

logger = structlog.get_logger()

ORIGIN_SCOUTING = "reip_scouting"
ITEMS_PER_FEED = 40
REQUEST_TIMEOUT = 20.0
# Feeds routinely put HTML in the description; the AI reads text, and so does the
# person who ends up looking at the signal.
_TAGS = re.compile(r"<[^>]+>")
_ATOM = "{http://www.w3.org/2005/Atom}"


def _text(node: Optional[Any]) -> str:
    return _TAGS.sub(" ", (node.text or "")).strip() if node is not None else ""


def _first(node: Any, *tags: str) -> Optional[Any]:
    """First tag present. An ElementTree element with no children is falsy, so
    `node.find(a) or node.find(b)` silently prefers the second one."""
    for tag in tags:
        found = node.find(tag)
        if found is not None:
            return found
    return None


def _parse_date(raw: str) -> Optional[datetime]:
    if not raw:
        return None
    for parse in (
        lambda v: datetime.fromisoformat(v.replace("Z", "+00:00")),
        lambda v: datetime.strptime(v, "%a, %d %b %Y %H:%M:%S %z"),
        lambda v: datetime.strptime(v, "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=timezone.utc),
    ):
        try:
            return parse(raw.strip())
        except (ValueError, TypeError):
            continue
    return None


def parse_feed(xml: str) -> list[dict]:
    """Items of an RSS or Atom feed, in one shape.

    Pure and separately testable: feeds are the kind of input that arrives
    malformed, and a broken feed must not take the collection run with it.
    """
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as e:
        logger.warning("RSS: не удалось разобрать ленту", error=str(e))
        return []

    items: list[dict] = []
    for node in list(root.iter("item")) + list(root.iter(f"{_ATOM}entry")):
        link_node = _first(node, "link", f"{_ATOM}link")
        link = _text(link_node) or (link_node.get("href") if link_node is not None else "")
        title = _text(_first(node, "title", f"{_ATOM}title"))
        body = _text(_first(node, "description", f"{_ATOM}summary", f"{_ATOM}content"))
        guid = _text(_first(node, "guid", f"{_ATOM}id")) or link
        published = _parse_date(
            _text(_first(node, "pubDate", f"{_ATOM}updated", f"{_ATOM}published"))
        )
        if not (title or body):
            continue
        items.append({
            "id": guid or link or title,
            "url": link or None,
            "title": title,
            "text": f"{title}\n{body}".strip(),
            "published_at": published,
        })
    return items[:ITEMS_PER_FEED]


class RssCollector:
    """Reads one feed per source row and turns matching items into signals."""

    def __init__(self):
        self._client = None

    def is_available(self) -> bool:
        # A feed needs no key; the source list is the switch.
        return True

    async def _get_client(self):
        import httpx  # noqa: PLC0415

        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT, follow_redirects=True,
                headers={"User-Agent": "REIP/1.0 (+https://reip.grouvi.online)"},
            )
        return self._client

    async def fetch(self, url: str) -> list[dict]:
        client = await self._get_client()
        try:
            res = await client.get(url)
            res.raise_for_status()
        except Exception as e:  # noqa: BLE001 - network, TLS, anything
            logger.warning("RSS: лента недоступна", url=url, error=str(e))
            return []
        return parse_feed(res.text)

    async def collect_from_source(self, session, source, geo_keywords: dict[str, Any],
                                  limit: int = ITEMS_PER_FEED) -> int:
        """Ingest a feed; create signals for items that pass the cheap filter."""
        from sqlalchemy import select  # noqa: PLC0415

        from app.models.signal import Signal  # noqa: PLC0415
        from app.services.channels.base import author_hash  # noqa: PLC0415
        from app.services.signal_bus import ingest_content  # noqa: PLC0415

        url = source.source_url
        if not url:
            return 0

        created = 0
        for item in (await self.fetch(url))[:limit]:
            raw = {
                "id": item["id"],
                "url": item["url"],
                "text": item["text"],
                "content_type": "post",
                "published_at": item["published_at"],
                "author_name": None,
            }
            cu = await ingest_content(session, source.agency_id, "rss", raw,
                                      source_id=source.id)
            if cu is None:
                continue
            exists = await session.scalar(
                select(Signal.id).where(Signal.content_unit_id == cu.id))
            if exists:
                continue
            if not quick_filter(item["text"], geo_keywords):
                continue

            session.add(Signal(
                agency_id=source.agency_id,
                source_id=source.id,
                geo_location_id=source.geo_location_id,
                content_unit_id=cu.id,
                raw_text=item["text"],
                author_hash=author_hash("rss", item["id"]),
                signal_url=item["url"],
                origin_system=ORIGIN_SCOUTING,
                reply_channel=None,  # a feed is read-only: no channel to answer on
                status="new",
            ))
            created += 1

        if created:
            await session.commit()
        logger.info("RSS collect", source=url, signals_created=created)
        return created

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
