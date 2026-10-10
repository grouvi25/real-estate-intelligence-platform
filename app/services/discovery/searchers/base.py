"""What every platform searcher looks like."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional

from app.services.discovery.types import KeywordMatrix, SourceCandidate

ACTIVE = "active"        # works now
NEEDS_KEY = "needs_key"  # implemented, waits for a key in .env
STUB = "stub"            # no working open access; see the module docstring


@dataclass
class SearchContext:
    clients: object                      # PlatformClients
    guard: object                        # RateLimitGuard
    agency_id: uuid.UUID
    geo_id: Optional[uuid.UUID]
    city: str
    session: object = None               # DB session, for forum seeds
    competitors_found: list[str] = field(default_factory=list)
    trends: dict = field(default_factory=dict)


class Searcher:
    platform: str = ""
    title: str = ""
    why_unavailable: str = ""

    def state(self) -> str:
        return ACTIVE

    async def search(self, kw: KeywordMatrix, ctx: SearchContext) -> list[SourceCandidate]:
        raise NotImplementedError


class StubSearcher(Searcher):
    """A platform the ТЗ lists but which has no working open access. Kept as a
    named stub so the run log says why it found nothing."""

    def state(self) -> str:
        return STUB

    async def search(self, kw: KeywordMatrix, ctx: SearchContext) -> list[SourceCandidate]:
        return []
