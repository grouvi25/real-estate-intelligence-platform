"""VK adapter. Signal Bus addendum.

Ingests VK wall posts / comments and posts replies via the VK API using the
agency's service token. If no token is configured, reply degrades gracefully.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import structlog

from app.config import config
from app.services.channels.base import ChannelAdapter, NormalizedContent, author_hash

logger = structlog.get_logger()


def _parse_unix(value: object) -> Optional[datetime]:
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc) if value else None
    except (TypeError, ValueError, OSError):
        return None


class VkAdapter(ChannelAdapter):
    channel = "vk"

    def normalize(self, raw: dict) -> NormalizedContent:
        owner_id = raw.get("owner_id")
        post_id = raw.get("id")
        external_id = f"{owner_id}_{post_id}" if owner_id and post_id else (
            str(post_id) if post_id else None
        )
        url = raw.get("url") or (f"https://vk.com/wall{external_id}" if external_id else None)
        return NormalizedContent(
            channel=self.channel,
            external_id=external_id,
            url=url,
            content_type=raw.get("content_type", "post"),
            raw_content=raw.get("text") or "",
            author_hash=author_hash(self.channel, raw.get("from_id") or owner_id),
            author_display_name=raw.get("author_name"),
            published_at=_parse_unix(raw.get("date")),
            meta={"owner_id": owner_id} if owner_id else {},
        )

    def reply_supported(self) -> bool:
        return bool(config.vk_service_token)

    async def send_reply(self, target: str, text: str) -> dict:
        """Post a comment via wall.createComment. target = "ownerId_postId"."""
        if not config.vk_service_token:
            return {"sent": False, "reason": "vk_not_configured", "channel": self.channel}
        try:
            owner_id, post_id = target.split("_", 1)
        except ValueError:
            return {"sent": False, "reason": "bad_target", "channel": self.channel}

        try:
            import httpx

            params = {
                "owner_id": owner_id,
                "post_id": post_id,
                "message": text,
                "access_token": config.vk_service_token,
                "v": config.vk_api_version,
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post("https://api.vk.com/method/wall.createComment",
                                         data=params)
            ok = resp.status_code < 400 and "error" not in resp.json()
            return {"sent": ok, "channel": self.channel}
        except Exception as e:  # noqa: BLE001
            logger.warning("VK reply failed", error=str(e))
            return {"sent": False, "reason": "transport_error", "channel": self.channel}
