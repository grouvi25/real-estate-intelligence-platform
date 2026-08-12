"""Channel adapter registry. Signal Bus addendum.

get_channel_adapter("avito"|"cian"|"telegram"|"max"|"vk"|"youtube"|"rss") returns a shared
adapter instance. Unknown channels return None so callers can degrade cleanly.
"""
from __future__ import annotations

from typing import Optional

from app.services.channels.base import ChannelAdapter, NormalizedContent
from app.services.channels.classifieds import AvitoAdapter, CianAdapter
from app.services.channels.messaging import (
    MaxAdapter,
    RssAdapter,
    TelegramAdapter,
    YoutubeAdapter,
)
from app.services.channels.vk import VkAdapter

_ADAPTERS: dict[str, ChannelAdapter] = {
    "avito": AvitoAdapter(),
    "avito_api": AvitoAdapter(),
    "cian": CianAdapter(),
    "cian_api": CianAdapter(),
    "telegram": TelegramAdapter(),
    "tg_bot": TelegramAdapter(),
    "max": MaxAdapter(),
    "max_bot": MaxAdapter(),
    "vk": VkAdapter(),
    "vk_api": VkAdapter(),
    # Read-only: collected from, never answered on.
    "youtube": YoutubeAdapter(),
    "rss": RssAdapter(),
}

SUPPORTED_CHANNELS = ("avito_api", "cian_api", "tg_bot", "max_bot", "vk_api", "youtube", "rss")


def get_channel_adapter(channel: str) -> Optional[ChannelAdapter]:
    return _ADAPTERS.get((channel or "").lower())


__all__ = [
    "ChannelAdapter",
    "NormalizedContent",
    "get_channel_adapter",
    "SUPPORTED_CHANNELS",
]
