"""Telegram & MAX messaging adapters. Signal Bus addendum.

Both deliver replies through the shared bot abstraction layer, so replies reuse
the same bot credentials and error handling as manager notifications.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.services.channels.base import ChannelAdapter, NormalizedContent, author_hash


def _parse_unix(value: object) -> Optional[datetime]:
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc) if value else None
    except (TypeError, ValueError, OSError):
        return None


class TelegramAdapter(ChannelAdapter):
    channel = "telegram"

    def normalize(self, raw: dict) -> NormalizedContent:
        chat = raw.get("chat") or {}
        sender = raw.get("from") or {}
        chat_id = chat.get("id")
        message_id = raw.get("message_id")
        external_id = f"{chat_id}:{message_id}" if chat_id and message_id else None
        display = sender.get("username") or sender.get("first_name")
        return NormalizedContent(
            channel=self.channel,
            external_id=external_id,
            url=raw.get("url"),
            content_type="message",
            raw_content=raw.get("text") or raw.get("caption") or "",
            author_hash=author_hash(self.channel, sender.get("id")),
            author_display_name=display,
            published_at=_parse_unix(raw.get("date")),
            meta={"chat_id": chat_id} if chat_id else {},
        )

    def reply_supported(self) -> bool:
        return True

    async def send_reply(self, target: str, text: str) -> dict:
        from app.services.bot_abstraction import BotMessage, BotPlatform, bot_layer

        # target is a chat id (optionally "chat_id:message_id").
        chat_id = int(str(target).split(":", 1)[0])
        ok = await bot_layer.send_message(chat_id, BotPlatform.TELEGRAM, BotMessage(text=text))
        return {"sent": ok, "channel": self.channel}


class MaxAdapter(ChannelAdapter):
    channel = "max"

    def normalize(self, raw: dict) -> NormalizedContent:
        sender = raw.get("from") or raw.get("sender") or {}
        return NormalizedContent(
            channel=self.channel,
            external_id=str(raw["id"]) if raw.get("id") is not None else None,
            url=raw.get("url"),
            content_type="message",
            raw_content=raw.get("text") or "",
            author_hash=author_hash(self.channel, sender.get("id") or raw.get("user_id")),
            author_display_name=sender.get("name"),
            published_at=_parse_unix(raw.get("timestamp") or raw.get("date")),
            meta={},
        )

    def reply_supported(self) -> bool:
        return True

    async def send_reply(self, target: str, text: str) -> dict:
        from app.services.bot_abstraction import BotMessage, BotPlatform, bot_layer

        ok = await bot_layer.send_message(int(target), BotPlatform.MAX, BotMessage(text=text))
        return {"sent": ok, "channel": self.channel}
