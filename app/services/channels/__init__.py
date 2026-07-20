"""Channel adapter registry. Signal Bus addendum.

get_channel_adapter("avito"|"cian"|"telegram"|"max"|"vk") returns a shared
adapter instance. Unknown channels return None so callers can degrade cleanly.
"""
from __future__ import annotations

from typing import Optional

from app.services.channels.base import ChannelAdapter, NormalizedContent
from app.services.channels.classifieds import AvitoAdapter, CianAdapter
from app.services.channels.messaging import MaxAdapter, TelegramAdapter
from app.services.channels.vk import VkAdapter

_ADAPTERS: dict[str, ChannelAdapter] = {
    "avito": AvitoAdapter(),
    "cian": CianAdapter(),
    "telegram": TelegramAdapter(),
    "max": MaxAdapter(),
    "vk": VkAdapter(),
}

SUPPORTED_CHANNELS = tuple(_ADAPTERS.keys())


def get_channel_adapter(channel: str) -> Optional[ChannelAdapter]:
    return _ADAPTERS.get((channel or "").lower())


__all__ = [
    "ChannelAdapter",
    "NormalizedContent",
    "get_channel_adapter",
    "SUPPORTED_CHANNELS",
]
