"""YouTube collector: comments under regional videos. TZ section 3 manifest.

The schema allowed a source of type 'youtube' from the first migration and
nothing ever read one. What is actually here is not the videos but the comments
under them: a walkthrough of a Геленджик complex collects "а сколько стоит
двушка с видом?" underneath, and that is a buyer asking in public.

Credential-gated exactly like the other collectors: without YOUTUBE_API_KEY
every method is a no-op, so nothing changes for anyone who has not supplied one.

Quota, because it is small and easy to burn: the Data API allows 10 000 units a
day, a commentThreads.list page costs 1, and a search costs 100 — which is why
this reads comments on known channels rather than searching for videos.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

import structlog

from app.config import config
from app.services.intent_scoring import quick_filter

logger = structlog.get_logger()

API_BASE = "https://www.googleapis.com/youtube/v3"
ORIGIN_SCOUTING = "reip_scouting"
VIDEOS_PER_CHANNEL = 5
COMMENTS_PER_VIDEO = 50
REQUEST_TIMEOUT = 20.0


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class YoutubeCollector:
    def __init__(self):
        self.key = config.youtube_api_key
        self._client = None

    def is_available(self) -> bool:
        return bool(self.key)

    async def _get_client(self):
        import httpx  # noqa: PLC0415

        if self._client is None:
            self._client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT)
        return self._client

    async def _call(self, endpoint: str, **params) -> Optional[dict]:
        """One API call. Returns the payload, or None on any failure.

        Quota exhaustion answers 403 with a body that names it; worth saying in
        words, since the symptom is otherwise "collection quietly stopped".
        """
        if not self.is_available():
            return None
        client = await self._get_client()
        try:
            res = await client.get(f"{API_BASE}/{endpoint}", params={**params, "key": self.key})
            if res.status_code == 403:
                logger.warning("YouTube: отказано — вероятно, исчерпана дневная квота",
                               endpoint=endpoint, body=res.text[:200])
                return None
            res.raise_for_status()
            return res.json()
        except Exception as e:  # noqa: BLE001 - network, JSON, anything
            logger.warning("YouTube call failed", endpoint=endpoint, error=str(e))
            return None

    @staticmethod
    def _channel_id(source) -> Optional[str]:
        """Channel id from external_id or a /channel/<id> URL."""
        if source.external_id:
            return str(source.external_id)
        url = source.source_url or ""
        if "/channel/" in url:
            # .../channel/UC456/videos?x=1 -> UC456
            tail = url.split("/channel/")[-1]
            return tail.split("?")[0].split("/")[0].strip() or None
        return None

    async def _recent_video_ids(self, channel_id: str) -> list[str]:
        """Latest uploads, read through the uploads playlist.

        playlistItems costs 1 unit where search.list costs 100, and this runs on
        a schedule — the difference is the whole daily quota.
        """
        channel = await self._call("channels", part="contentDetails", id=channel_id)
        items = (channel or {}).get("items") or []
        if not items:
            return []
        uploads = (items[0].get("contentDetails", {})
                   .get("relatedPlaylists", {}).get("uploads"))
        if not uploads:
            return []

        playlist = await self._call("playlistItems", part="contentDetails",
                                    playlistId=uploads, maxResults=VIDEOS_PER_CHANNEL)
        return [
            item["contentDetails"]["videoId"]
            for item in (playlist or {}).get("items", [])
            if item.get("contentDetails", {}).get("videoId")
        ]

    async def _comments(self, video_id: str) -> list[dict]:
        response = await self._call(
            "commentThreads", part="snippet", videoId=video_id,
            maxResults=COMMENTS_PER_VIDEO, order="time", textFormat="plainText")
        comments = []
        for thread in (response or {}).get("items", []):
            top = (thread.get("snippet", {})
                   .get("topLevelComment", {}).get("snippet", {}))
            text = (top.get("textDisplay") or "").strip()
            if not text:
                continue
            comments.append({
                "id": thread.get("id"),
                "text": text,
                "author": top.get("authorDisplayName"),
                "author_id": (top.get("authorChannelId") or {}).get("value"),
                "published_at": _parse_ts(top.get("publishedAt")),
                "url": f"https://www.youtube.com/watch?v={video_id}&lc={thread.get('id')}",
            })
        return comments

    async def collect_from_source(self, session, source, geo_keywords: dict[str, Any],
                                  limit: int = COMMENTS_PER_VIDEO) -> int:
        """Read comments under a channel's recent videos; create signals."""
        if not self.is_available():
            return 0

        from sqlalchemy import select  # noqa: PLC0415

        from app.models.signal import Signal  # noqa: PLC0415
        from app.services.channels.base import author_hash  # noqa: PLC0415
        from app.services.signal_bus import ingest_content  # noqa: PLC0415

        channel_id = self._channel_id(source)
        if not channel_id:
            return 0

        created = 0
        for video_id in await self._recent_video_ids(channel_id):
            for comment in (await self._comments(video_id))[:limit]:
                raw = {
                    "id": comment["id"],
                    "url": comment["url"],
                    "text": comment["text"],
                    "content_type": "comment",
                    "published_at": comment["published_at"],
                    "author_name": comment["author"],
                }
                cu = await ingest_content(session, source.agency_id, "youtube", raw,
                                          source_id=source.id)
                if cu is None:
                    continue
                exists = await session.scalar(
                    select(Signal.id).where(Signal.content_unit_id == cu.id))
                if exists:
                    continue
                if not quick_filter(comment["text"], geo_keywords):
                    continue

                session.add(Signal(
                    agency_id=source.agency_id,
                    source_id=source.id,
                    geo_location_id=source.geo_location_id,
                    content_unit_id=cu.id,
                    raw_text=comment["text"],
                    author_hash=author_hash("youtube", comment["author_id"]),
                    author_display_name=comment["author"],
                    signal_url=comment["url"],
                    origin_system=ORIGIN_SCOUTING,
                    # Answering a YouTube comment needs the channel's own
                    # account, which the agency has and we do not.
                    reply_channel=None,
                    status="new",
                ))
                created += 1

        if created:
            await session.commit()
        logger.info("YouTube collect", channel=channel_id, signals_created=created)
        return created

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
