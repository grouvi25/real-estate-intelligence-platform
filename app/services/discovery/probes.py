"""Read the latest posts of a source or candidate, whatever the platform.

Used by the sandbox test (what is posted there) and by the health check (is
anything posted at all). Returns None when the source cannot be read -- deleted,
closed, wrong id, platform down -- and a list, possibly empty, when it can.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import structlog

from app.services.discovery.types import FORUM, RSS, TELEGRAM, TG_CATALOG, VK, YOUTUBE, Post

logger = structlog.get_logger()

PLATFORM_OF_SOURCE_TYPE = {
    "telegram_chat": TELEGRAM,
    "telegram_channel": TELEGRAM,
    "vk_group": VK,
    "youtube": YOUTUBE,
    "rss": RSS,
    "forum": RSS,
    "website": RSS,
}


def _ts(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


async def telegram_posts(clients, handle: str, n: int) -> Optional[list[Post]]:
    client = await clients.telegram()
    if client is None or not handle:
        return None
    try:
        posts = []
        async for msg in client.iter_messages(handle.lstrip("@"), limit=n):
            posts.append(Post(text=(getattr(msg, "message", None) or "").strip(),
                              at=_ts(getattr(msg, "date", None))))
        return posts
    except Exception as e:  # noqa: BLE001 - private, deleted, renamed, flood
        logger.info("Telegram source unreadable", handle=handle, error=str(e)[:120])
        return None


async def vk_posts(clients, domain: str, n: int) -> Optional[list[Post]]:
    vk = clients.vk()
    if vk is None or not domain:
        return None
    response = await vk._call("wall.get", domain=domain.lstrip("@"), count=n)
    if response is None:
        # Wall disabled is an error too; the group may still talk in обсуждения.
        texts = await vk._board_samples(domain, min(n, 10))
        return [Post(text=t) for t in texts] if texts else None
    items = response.get("items") or []
    if not items:
        texts = await vk._board_samples(domain, min(n, 10))
        return [Post(text=t) for t in texts]
    return [Post(text=(i.get("text") or "").strip(), at=_ts(i.get("date"))) for i in items]


async def youtube_posts(clients, channel_id: str, n: int) -> Optional[list[Post]]:
    """Latest uploads (title + description) -- 2 quota units, not search's 100."""
    yt = clients.youtube()
    if yt is None or not channel_id:
        return None
    channel = await yt._call("channels", part="contentDetails", id=channel_id)
    items = (channel or {}).get("items") or []
    if channel is None:
        return None
    if not items:
        return None  # the channel is gone
    uploads = items[0].get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
    if not uploads:
        return []
    playlist = await yt._call("playlistItems", part="snippet", playlistId=uploads,
                              maxResults=min(n, 50))
    if playlist is None:
        return None
    posts = []
    for item in playlist.get("items") or []:
        sn = item.get("snippet") or {}
        posts.append(Post(text=f"{sn.get('title', '')}\n{sn.get('description', '')}".strip(),
                          at=_ts(sn.get("publishedAt"))))
    return posts


async def feed_posts(clients, url: str, n: int) -> Optional[list[Post]]:
    from app.collectors.rss_collector import parse_feed  # noqa: PLC0415

    if not url:
        return None
    http = await clients.http()
    try:
        res = await http.get(url)
        if res.status_code >= 400:
            return None
        items = parse_feed(res.text)
    except Exception as e:  # noqa: BLE001
        logger.info("Feed unreadable", url=url, error=str(e)[:120])
        return None
    if not items and "<rss" not in res.text[:500].lower() and "<feed" not in res.text[:500].lower():
        return None  # not a feed at all
    return [Post(text=i.get("text") or "", at=_ts(i.get("published_at"))) for i in items[:n]]


async def fetch_posts(clients, platform: str, ref: str, n: int = 20) -> Optional[list[Post]]:
    """``ref`` — Telegram handle, VK screen name, YouTube channel id or feed URL."""
    if platform in (TELEGRAM, TG_CATALOG):
        return await telegram_posts(clients, ref, n)
    if platform == VK:
        return await vk_posts(clients, ref, n)
    if platform == YOUTUBE:
        return await youtube_posts(clients, ref, n)
    if platform in (RSS, FORUM):
        return await feed_posts(clients, ref, n)
    return None


def source_ref(source) -> tuple[Optional[str], Optional[str]]:
    """(platform, ref) for a stored source, the way its collector resolves it."""
    platform = PLATFORM_OF_SOURCE_TYPE.get(source.source_type)
    url = source.source_url or ""
    external = str(source.external_id or "").strip()
    if platform == TELEGRAM:
        from app.collectors.telegram_collector import TelegramCollector  # noqa: PLC0415

        return platform, TelegramCollector._username(source)
    if platform == VK:
        from app.collectors.vk_collector import VkCollector  # noqa: PLC0415

        return platform, VkCollector._domain(source)
    if platform == YOUTUBE:
        from app.collectors.youtube_collector import YoutubeCollector  # noqa: PLC0415

        return platform, YoutubeCollector._channel_id(source)
    if platform == RSS:
        return platform, url or external or None
    return None, None
