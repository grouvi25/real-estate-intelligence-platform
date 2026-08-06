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
    board.*            user, service
    newsfeed.search    user, service
    groups.search      user only

So a service key reads groups fine and cannot search for them. Auto-discovery is
not lost to that, though: newsfeed.search does take a service key, and every post
it returns carries the id of the group that published it. Searching the feed and
counting publishers finds the groups that keep posting about the city -- measured
on Геленджик, five queries surfaced 103 groups including every large local
барахолка. So groups.search is tried first and the feed is harvested when the key
cannot call it.

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
# What a service key gets on a method VK marks "user only". Verified against the
# live API with a real service token: groups.search answers 15 "Access denied",
# not the 28 the schema suggested -- so the list covers both.
TOKEN_TOO_WEAK = (5, 15, 28)
# VK rejects long bursts; discovery runs weekly and collection every 10 minutes,
# so a small page size keeps well inside the service-token limits.
SEARCH_LIMIT = 20
WALL_LIMIT = 50
COMMENTS_PER_POST = 20
# Classified groups routinely disable the wall and run on обсуждения instead --
# "Access denied: wall is disabled" is what both Геленджик boards returned. Board
# topics take a service token too, so they are read as a fallback.
TOPICS_TO_SCAN = 5
COMMENTS_PER_TOPIC = 50
# Buyers ask in the comments far more often than they post on a group wall.
POSTS_TO_SCAN_FOR_COMMENTS = 10
# Feed harvesting: how many posts to look at per query, and the floor a group has
# to clear to be worth an AI evaluation. A regional feed search drags in unrelated
# groups ("Новости Тольятти" answered "Геленджик квартира"), so a candidate also
# has to mention one of the search words in its name or description.
NEWSFEED_LIMIT = 200
MIN_MEMBERS = 300
WORD_PREFIX = 6  # "квартиру" and "квартира" have to match each other


class VkCollector:
    def __init__(self):
        self.token = config.vk_service_token
        self.version = config.vk_api_version
        self._client = None
        # Set when VK refuses a method as beyond this key; search_groups reads it
        # to decide whether to fall back to the feed.
        self.token_too_weak = False

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
                self.token_too_weak = True
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

        groups.search is marked "user only", so a service key falls back to
        harvesting the publishers out of newsfeed.search.
        """
        if not self.is_available():
            return []

        queries = queries[:12]
        seen: dict[str, dict] = {}
        for query in queries:
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

        if not seen and self.token_too_weak:
            seen = await self._harvest_groups(queries, limit)

        await self._enrich(list(seen.values()))
        return list(seen.values())

    async def _harvest_groups(self, queries: list[str], limit: int) -> dict[str, dict]:
        """Find groups through the feed instead of the group directory.

        newsfeed.search accepts a service key, and every post it returns names its
        publisher. Counting publishers therefore answers the same question
        groups.search would have: which groups keep writing about this city.

        The feed is looser than the directory -- "Новости Тольятти" came back for
        "Геленджик квартира" -- so a candidate has to mention one of the search
        words itself before it costs an AI evaluation.
        """
        from collections import Counter  # noqa: PLC0415

        posts_by_group: Counter = Counter()
        for query in queries:
            response = await self._call("newsfeed.search", q=query, count=NEWSFEED_LIMIT)
            for item in (response or {}).get("items", []):
                owner_id = item.get("owner_id") or 0
                if owner_id < 0:  # negative owner == group, positive == person
                    posts_by_group[-owner_id] += 1

        if not posts_by_group:
            return {}

        stems = self._stems(queries)
        ranked = [gid for gid, _ in posts_by_group.most_common(limit * 4)]
        response = await self._call(
            "groups.getById", group_ids=",".join(str(g) for g in ranked),
            fields="members_count,description")
        groups = (response or {}).get("groups") if isinstance(response, dict) else response

        found: dict[str, dict] = {}
        for group in sorted(groups or [], key=lambda g: -(g.get("members_count") or 0)):
            screen_name = group.get("screen_name")
            text = f"{group.get('name') or ''} {group.get('description') or ''}".lower()
            if not screen_name or group.get("is_closed"):
                continue
            if (group.get("members_count") or 0) < MIN_MEMBERS:
                continue
            if not any(stem in text for stem in stems):
                continue
            found[screen_name] = {
                "id": str(group.get("id")),
                "name": group.get("name") or screen_name,
                "username": screen_name,
                "url": f"https://vk.com/{screen_name}",
                "members": group.get("members_count") or 0,
                "description": group.get("description") or "",
                "samples": [],
            }
            if len(found) >= limit:
                break

        logger.info("VK: группы найдены через ленту (ключ не умеет groups.search)",
                    seen=len(posts_by_group), kept=len(found))
        return found

    @staticmethod
    def _stems(queries: list[str]) -> set[str]:
        """Search words cut short so declensions still match: a group called
        «Барахолка Геленджика» has to match the query «Геленджик квартира»."""
        return {
            word[:WORD_PREFIX]
            for query in queries
            for word in query.lower().split()
            if len(word) >= WORD_PREFIX
        }

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
        entries = await self._entries(posts)
        if not entries:
            entries = await self._board_entries(source)

        for entry in entries:
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

    async def _board_entries(self, source) -> list[dict]:
        """Read обсуждения when the wall gives nothing.

        A group with a disabled wall is not a dead group: on Геленджик boards the
        wall is off and every listing sits in a topic.
        """
        group_id = await self._group_id(source)
        if not group_id:
            return []

        topics = await self._call("board.getTopics", group_id=group_id, count=TOPICS_TO_SCAN)
        entries: list[dict] = []
        for topic in (topics or {}).get("items", []):
            topic_id = topic.get("id")
            if not topic_id:
                continue
            comments = await self._call(
                "board.getComments", group_id=group_id, topic_id=topic_id,
                count=COMMENTS_PER_TOPIC)
            for c in (comments or {}).get("items", []):
                entries.append({
                    **c,
                    "content_type": "comment",
                    "owner_id": -int(group_id),
                    "url": f"https://vk.com/topic-{group_id}_{topic_id}?post={c.get('id')}",
                    "author_name": None,
                })
        return entries

    async def _group_id(self, source) -> Optional[int]:
        """Numeric group id, needed by the board methods."""
        if source.meta and source.meta.get("vk_group_id"):
            return int(source.meta["vk_group_id"])
        domain = self._domain(source)
        if not domain:
            return None
        response = await self._call("groups.getById", group_id=domain)
        groups = (response or {}).get("groups") if isinstance(response, dict) else response
        if not groups:
            return None
        try:
            return int(groups[0]["id"])
        except (KeyError, IndexError, TypeError, ValueError):
            return None

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
