"""Shapes passed between the discovery components."""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

# Platform names used by searchers, the rate guard and discovery_candidates.
TELEGRAM = "telegram"
VK = "vk"
YOUTUBE = "youtube"
RSS = "rss"
FORUM = "forum"
TG_CATALOG = "tg_catalog"
CLASSIFIEDS = "classifieds"
YANDEX_MAPS = "yandex_maps"
OTZOVIK = "otzovik"
WORDSTAT = "wordstat"

# Which sources.source_type a candidate of each platform becomes. Platforms that
# never produce a readable source (maps, review sites, wordstat) are absent.
SOURCE_TYPE = {
    TELEGRAM: "telegram_chat",
    TG_CATALOG: "telegram_chat",
    VK: "vk_group",
    YOUTUBE: "youtube",
    RSS: "rss",
    FORUM: "rss",
}


@dataclass
class KeywordMatrix:
    city: str
    city_variations: list[str]
    intent_queries: list[str]
    niche_tags: list[str]
    competitor_names: list[str]
    # per-platform query lists from the city's AI vocabulary
    platform_queries: dict[str, list[str]] = field(default_factory=dict)

    def queries_for(self, platform: str) -> list[str]:
        return self.platform_queries.get(platform) or self.intent_queries


@dataclass
class Post:
    text: str
    at: Optional[datetime] = None


@dataclass
class SourceCandidate:
    platform: str
    external_id: str
    name: str
    url: str
    audience: int = 0
    last_post_at: Optional[datetime] = None
    posts_per_week: Optional[float] = None
    description: str = ""
    samples: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    rank_score: float = 0.0

    @property
    def key(self) -> str:
        return f"{self.platform}:{self.external_id}"

    @property
    def normalized_name(self) -> str:
        return normalize_name(self.name)


@dataclass
class SandboxResult:
    candidate: SourceCandidate
    sandbox_score: float
    is_alive: bool
    verdict: str  # ACTIVATE | SANDBOX | REJECT
    reason: str = ""
    # the test itself could not be done (AI down): keep the candidate for a
    # re-test, but do not turn it into a source on no evidence
    retry_only: bool = False


@dataclass
class DiscoveryReport:
    agency_id: uuid.UUID
    city: str
    found: int = 0
    passed_dup: int = 0
    tested: int = 0
    activated: int = 0
    sandboxed: int = 0
    rejected: int = 0
    by_platform: dict = field(default_factory=dict)
    errors: dict = field(default_factory=dict)
    duration_s: float = 0.0
    results: list[SandboxResult] = field(default_factory=list)


_NAME_NOISE = re.compile(r"[^0-9a-zа-яё]+")


def normalize_name(name: str) -> str:
    """Lower-case letters and digits only: «Недвижимость | Геленджик» and
    «недвижимость геленджик» are the same chat for the fuzzy duplicate check."""
    return _NAME_NOISE.sub(" ", (name or "").lower().replace("ё", "е")).strip()
