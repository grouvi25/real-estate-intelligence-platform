"""Channel adapter base. Signal Bus addendum.

A ChannelAdapter normalizes raw content from a source channel into a common
NormalizedContent shape (so the Signal Bus can persist content_units + signals
uniformly) and, where the channel supports it, sends a reply back.

Adapters keep ingestion (normalize, pure) separate from delivery (send_reply,
async I/O) so normalization is trivially unit-testable without network access.
"""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class NormalizedContent:
    channel: str
    external_id: Optional[str]
    url: Optional[str]
    content_type: str
    raw_content: str
    author_hash: Optional[str]
    author_display_name: Optional[str]
    published_at: Optional[datetime] = None
    meta: dict = field(default_factory=dict)


def author_hash(channel: str, author_id: object) -> Optional[str]:
    """Stable, non-reversible per-channel author id (152-FZ: no raw PII stored)."""
    if author_id in (None, ""):
        return None
    digest = hashlib.sha256(f"{channel}:{author_id}".encode()).hexdigest()
    return digest[:32]


class ChannelAdapter(ABC):
    channel: str = "unknown"

    @abstractmethod
    def normalize(self, raw: dict) -> NormalizedContent:
        """Map a raw platform payload into NormalizedContent."""

    def reply_supported(self) -> bool:
        """Whether send_reply can deliver on this channel."""
        return False

    async def send_reply(self, target: str, text: str) -> dict:
        """Deliver a reply. Default: unsupported (e.g. classifieds require manual)."""
        return {"sent": False, "reason": "reply_not_supported", "channel": self.channel}
