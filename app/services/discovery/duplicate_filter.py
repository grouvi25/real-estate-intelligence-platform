"""DuplicateFilter: never test what the agency already has. ТЗ «Сигналы» 2.5.

Exact: the same chat/group/channel/feed is already a source (by handle or URL)
or was already tested -- a rejected candidate is not re-tested every hour, and a
sandboxed one is re-tested by its own daily task (retry_sandbox_candidates), not
here. Fuzzy: a name ≥90% similar to
an existing source's is taken for a rebrand of it (difflib).

Telegram and the Telegram catalogue are one platform here: the same channel found
both ways is one candidate.
"""
from __future__ import annotations

import difflib
import uuid

from sqlalchemy import select

from app.services.discovery.types import TELEGRAM, TG_CATALOG, SourceCandidate, normalize_name

FUZZY_RATIO = 0.9


def _ident(platform: str, external_id: str) -> str:
    platform = TELEGRAM if platform == TG_CATALOG else platform
    return f"{platform}:{str(external_id).lower().lstrip('@').rstrip('/')}"


def _source_idents(source) -> set[str]:
    from app.services.discovery.probes import source_ref  # noqa: PLC0415

    out = set()
    platform, ref = source_ref(source)
    if platform and ref:
        out.add(_ident(platform, ref))
    if source.source_url:
        out.add("url:" + source.source_url.lower().rstrip("/"))
    return out


class DuplicateFilter:
    def __init__(self, session, agency_id: uuid.UUID):
        self.session = session
        self.agency_id = agency_id

    async def _known(self) -> tuple[set[str], list[str]]:
        from app.models.discovery import DiscoveryCandidate  # noqa: PLC0415
        from app.models.source import Source  # noqa: PLC0415

        sources = (await self.session.execute(
            select(Source).where(Source.agency_id == self.agency_id))).scalars().all()
        idents: set[str] = set()
        names: list[str] = []
        for s in sources:
            idents |= _source_idents(s)
            if s.source_name:
                names.append(normalize_name(s.source_name))
        for platform, external_id in (await self.session.execute(
                select(DiscoveryCandidate.platform, DiscoveryCandidate.external_id).where(
                    DiscoveryCandidate.agency_id == self.agency_id))).all():
            idents.add(_ident(platform, external_id))
        return idents, [n for n in names if n]

    async def check(self, candidates: list[SourceCandidate]) -> list[SourceCandidate]:
        idents, names = await self._known()
        out: list[SourceCandidate] = []
        for c in candidates:
            if _ident(c.platform, c.external_id) in idents or "url:" + c.url.lower().rstrip("/") in idents:
                continue
            name = c.normalized_name
            if name and any(difflib.SequenceMatcher(None, name, n).ratio() >= FUZZY_RATIO
                            for n in names):
                continue
            idents.add(_ident(c.platform, c.external_id))  # same thing found twice this run
            out.append(c)
        return out
