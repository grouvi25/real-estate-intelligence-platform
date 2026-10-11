"""CandidateRanker: who gets tested first. ТЗ «Сигналы» 2.4.

rank = 0.35·activity + 0.30·relevance + 0.20·audience + 0.15·density, each 0..1.

A searcher rarely knows everything: Telegram search gives no post dates, a news
feed has no audience. An unknown component counts as a neutral 0.5 rather than
zero, so a platform is not ranked down for what its search API does not say.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional

from app.services.discovery.types import SourceCandidate

WEIGHTS = {"activity": 0.35, "relevance": 0.30, "audience": 0.20, "density": 0.15}
NEUTRAL = 0.5


class CandidateRanker:
    def __init__(self, niche_tags: Optional[list[str]] = None,
                 city_variations: Optional[list[str]] = None, now=None):
        self.tags = [t.lower() for t in (niche_tags or [])]
        self.city = [c.lower() for c in (city_variations or [])]
        self._now = now or (lambda: datetime.now(timezone.utc))

    def _activity(self, c: SourceCandidate) -> float:
        if c.last_post_at is None:
            return NEUTRAL
        days = max(0.0, (self._now() - c.last_post_at).total_seconds() / 86400)
        return max(0.0, 1.0 - days / 30)  # today 1.0, a month of silence 0

    def _relevance(self, c: SourceCandidate) -> float:
        text = f"{c.name} {c.description}".lower().replace("ё", "е")
        if not text.strip():
            return NEUTRAL
        tag_hit = any(t in text for t in self.tags)
        city_hit = any(v[:max(5, len(v) - 2)] in text for v in self.city if v)
        return 0.5 * tag_hit + 0.5 * city_hit

    def _audience(self, c: SourceCandidate) -> float:
        if not c.audience:
            return NEUTRAL
        # 100 members ≈ 0.33, 10 000 ≈ 0.67, 1 000 000 = 1
        return min(1.0, math.log10(max(c.audience, 1)) / 6)

    def _density(self, c: SourceCandidate) -> float:
        words = " ".join(c.samples).lower().split()
        if not words:
            return NEUTRAL
        hits = sum(1 for w in words if any(t in w for t in self.tags))
        return min(1.0, hits / len(words) * 10)  # 10% target words is already a lot

    def score(self, c: SourceCandidate) -> float:
        return round(
            WEIGHTS["activity"] * self._activity(c)
            + WEIGHTS["relevance"] * self._relevance(c)
            + WEIGHTS["audience"] * self._audience(c)
            + WEIGHTS["density"] * self._density(c), 4)

    def rank(self, candidates: list[SourceCandidate]) -> list[SourceCandidate]:
        for c in candidates:
            c.rank_score = self.score(c)
        return sorted(candidates, key=lambda x: x.rank_score, reverse=True)
