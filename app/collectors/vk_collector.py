"""VK collector: find groups and read their walls. TZ section 3 manifest, 15.

VK was prepared everywhere except the part that reads it. The config carried
VK_SERVICE_TOKEN, sources.source_type allowed 'vk_group', the keyword builder
generated search_queries.vk_groups, and VkAdapter could normalise a post and even
post a reply -- but nothing ever called the VK API, so those search queries were
produced for no one and a vk_group source would simply be skipped by the
collector.

That matters beyond tidiness: Telegram's public search over Геленджик surfaced
eighteen chats and one of them was about buying property. VK groups are where a
regional audience of that size actually sits.

Token types, from VK's own API schema (VKCOM/vk-api-schema):

    wall.get           user, service
    wall.getComments   user, service
    groups.search      user only

So a service key reads groups fine and cannot search for them. That is a
supported way to run: add the groups by hand on the Источники screen and the
collector reads them. Auto-discovery of VK groups needs a user token, and when
the key cannot do it VK answers error 28 -- which this module reports in plain
words rather than as a bare code.

Credential-gated exactly like the Telegram collector: without VK_SERVICE_TOKEN
every method is a no-op, so dev and CI are unaffected.
"""
from __future__ import annotations

from typing import Any, Optional

import structlog

from app.config import config
from app.services.channels import get_channel_adapter
from app.services.intent_scoring import quick_filter

logger = structlog.get_logger()

API_BASE = "https://api.vk.com/method"
# 28 = application authorization failed, 5 = user authorization failed. Both are
# what a service key gets on a method VK marks "user only".
TOKEN_TOO_WEAK = (5, 28)
# VK rejects long bursts; discovery runs weekly and collection every 10 minutes,
# so a small page size keeps well inside the service-token limits.
SEARCH_LIMIT = 20
WALL_LIMIT = 50
COMMENTS_PER_POST = 20
# Buyers ask in the comments far more often than they post on a group wall.
POSTS_TO_SCAN_FOR_COMMENTS = 10


class VkCollector:
    def __init__(self):
        self.token = config.vk_service_token
        self.version = config.vk_api_version
        self._client = None

    def is_available(self) -> bool:
        return bool(self.token)

    async def _get_client(self):
        import httpx  # noqa: PLC0415

        if self._client is None:
            self._client = httpx.AsyncClient(timeout=20.0)
        return self._client

    async def _call(self, method: str, **params) -> Optional[dict]:
        """One API call. Returns the `response` payload, or None on any failure.

        VK reports errors with HTTP 200 and an `error` object, so the status code
        alone says nothing.
        """
        if not self.is_available():
            return None
        client = await self._get_client()
        try:
            res = await client.get(
                f"{API_BASE}/{method}",
                params={**params, "access_token": self.token, "v": self.version},
            )
            res.raise_for_status()
            body = res.json()
        except Exception as e:  # noqa: BLE001 - network, JSON, anything
            logger.warning("VK call failed", method=method, error=str(e))
            return None

        if "error" in body:
            err = body["error"]
            code = err.get("error_code")
            if code in TOKEN_TOO_WEAK:
                # Worth saying outright: the difference between "VK is broken"
                # and "this key cannot do that" is otherwise a bare number.
                logger.warning(
                    "VK: этот ключ не может вызвать метод — нужен пользовательский токен",
                    method=method, code=code, msg=err.get("error_msg"))
            else:
                logger.warning("VK API error", method=method,
                               code=code, msg=err.get("error_msg"))
            return None
        return body.get("response")

    async def search_groups(self, queries: list[str], limit: int = SEARCH_LIMIT) -> list[dict]:
        """Find candidate groups. Shaped like the Telegram collector's output so
        source_finder can score both the same way.

        Needs a user token: VK marks groups.search "user only". With a service
        key this returns [] and says why in the log; reading already-known groups
        is unaffected.
        """
        if not self.is_available():
            return []

        seen: dict[str, dict] = {}
        for query in queries[:12]:
            response = await self._call("groups.search", q=query, count=limit, type="group")
            for group in (response or {}).get("items", []):
                screen_name = group.get("screen_name")
                if not screen_name or group.get("is_closed"):
                    # A closed group cannot be read with a service token.
                    continue
                seen[screen_name] = {
                    "id": str(group.get("id")),
                    "name": group.get("name") or screen_name,
                    "username": screen_name,
                    "url": f"https://vk.com/{screen_name}",
                    "members": group.get("members_count") or 0,
                    "description": group.get("description") or "",
                    "samples": [],
                }
        await self._enrich(list(seen.values()))
        return list(seen.values())

    async def _enrich(self, candidates: list[dict], samples: int = 3) -> None:
        """Attach recent wall text so the AI scores content, not just a name.

        The Telegram side learned this the hard way: judged on its title alone,
        the one genuinely relevant chat scored 0.
        """
        for cand in candidates:
            response = await self._call(
                "wall.get", domain=cand["username"], count=samples * 4)
            texts = []
            for post in (response or {}).get("items", []):
                text = (post.get("text") or "").strip()
                if len(text) > 20:
                    texts.append(text[:280])
                if len(texts) >= samples:
                    break
            cand["samples"] = texts

    async def collect_from_source(
        self, session, source, geo_keywords: dict[str, Any], limit: int = WALL_LIMIT
    ) -> int:
        """Ingest a group's wall and comments; create signals for the promising.

        Returns the number of new signals created.
        """
        if not self.is_available():
            return 0

        from sqlalchemy import select  # noqa: PLC0415

        from app.models.signal import Signal  # noqa: PLC0415
        from app.services.signal_bus import ingest_content  # noqa: PLC0415

        domain = self._domain(source)
        if not domain:
            return 0

        adapter = get_channel_adapter("vk")
        created = 0
        response = await self._call("wall.get", domain=domain, count=limit)
        posts = (response or {}).get("items", [])

        for entry in await self._entries(posts):
            text = entry.get("text") or ""
            cu = await ingest_content(session, source.agency_id, "vk", entry,
                                      source_id=source.id)
            if cu is None:
                continue
            exists = await session.scalar(
                select(Signal.id).where(Signal.content_unit_id == cu.id))
            if exists:
                continue
            if not quick_filter(text, geo_keywords):
                continue

            norm = adapter.normalize(entry)
            session.add(Signal(
                agency_id=source.agency_id,
                source_id=source.id,
                geo_location_id=source.geo_location_id,
                content_unit_id=cu.id,
                raw_text=text,
                author_hash=norm.author_hash,
                author_display_name=norm.author_display_name,
                signal_url=norm.url,
                origin_system="vk",
                reply_channel="vk",
                status="new",
            ))
            created += 1

        if created:
            await session.commit()
        logger.info("VK collect", source=domain, signals_created=created)
        return created

    async def _entries(self, posts: list[dict]) -> list[dict]:
        """Wall posts, then comments under the most recent ones.

        Comments matter more than the posts: on a regional group the wall is
        mostly agency listings, while a buyer asks "посоветуйте район" underneath.
        """
        entries = [
            {**post, "content_type": "post", "url": self._post_url(post),
             "author_name": None}
            for post in posts
        ]

        for post in posts[:POSTS_TO_SCAN_FOR_COMMENTS]:
            owner_id, post_id = post.get("owner_id"), post.get("id")
            if not (owner_id and post_id):
                continue
            response = await self._call(
                "wall.getComments", owner_id=owner_id, post_id=post_id,
                count=COMMENTS_PER_POST, thread_items_count=0)
            for comment in (response or {}).get("items", []):
                entries.append({
                    **comment,
                    "content_type": "comment",
                    "owner_id": owner_id,
                    "url": f"https://vk.com/wall{owner_id}_{post_id}?reply={comment.get('id')}",
                    "author_name": None,
                })
        return entries

    @staticmethod
    def _post_url(post: dict) -> Optional[str]:
        owner_id, post_id = post.get("owner_id"), post.get("id")
        return f"https://vk.com/wall{owner_id}_{post_id}" if owner_id and post_id else None

    @staticmethod
    def _domain(source) -> Optional[str]:
        """Group screen name, from external_id or the URL."""
        if source.external_id:
            return str(source.external_id).lstrip("@")
        url = source.source_url or ""
        if "vk.com/" in url:
            return url.split("vk.com/")[-1].strip("/") or None
        return None

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


async def search_candidate_groups(queries: list[str], limit: int = SEARCH_LIMIT) -> list[dict]:
    """Module-level helper used by Source Discovery."""
    collector = VkCollector()
    try:
        return await collector.search_groups(queries, limit=limit)
    finally:
        await collector.close()
