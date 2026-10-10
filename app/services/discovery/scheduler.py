"""DiscoveryScheduler: one discovery run for one city of one agency. ТЗ «Сигналы» 2.1.

    keywords -> search on every enabled platform (in parallel, 120 s each)
      -> rank -> drop duplicates -> rate guard -> at most max_new_sources_per_run
      -> sandbox test -> discovery_candidates + sources + discovery_log

Two workers never run the same city at once (a Redis lock on the run key), and a
platform that fails is written to the log's errors and does not stop the others.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import select

from app.services.discovery.candidate_ranker import CandidateRanker
from app.services.discovery.clients import PlatformClients
from app.services.discovery.duplicate_filter import DuplicateFilter
from app.services.discovery.keyword_builder import KeywordBuilder
from app.services.discovery.rate_limit_guard import RateLimitGuard, redis_client
from app.services.discovery.sandbox_tester import SandboxTester
from app.services.discovery.searchers import all_searchers
from app.services.discovery.searchers.base import STUB, SearchContext
from app.services.discovery.settings import (
    AUTO_COMPETITORS_KEY,
    competitor_names_of,
    discovery_settings,
    platform_enabled,
)
from app.services.discovery.types import (
    RSS,
    SOURCE_TYPE,
    TELEGRAM,
    TG_CATALOG,
    DiscoveryReport,
    SandboxResult,
)

logger = structlog.get_logger()

SEARCH_TIMEOUT = 120
RUN_LOCK = "discovery:run:{geo}"
RUN_LOCK_TTL = 30 * 60
MAX_COMPETITORS = 100


def source_fields(result: SandboxResult) -> Optional[dict]:
    """What a candidate becomes in ``sources``, or None when it is not a source."""
    c = result.candidate
    source_type = SOURCE_TYPE.get(c.platform)
    if source_type is None:
        return None
    if c.platform == TG_CATALOG or (c.platform == TELEGRAM and c.meta.get("broadcast")):
        source_type = "telegram_channel"
    meta = {"discovery": {"platform": c.platform, "rank_score": c.rank_score}}
    if c.meta.get("vk_group_id"):
        meta["vk_group_id"] = c.meta["vk_group_id"]
    return {
        "source_type": source_type,
        "source_url": c.url,
        "source_name": (c.name or c.external_id)[:300],
        "external_id": None if c.platform in (RSS, "forum") else c.external_id,
        "status": "active" if result.verdict == "ACTIVATE" else "sandbox",
        "score": int(round(result.sandbox_score)),
        "sandbox_score": result.sandbox_score,
        "auto_found": True,
        "discovered_by": "discovery",
        "health_status": "healthy" if result.is_alive else "unknown",
        "last_post_at": c.last_post_at,
        "meta": meta,
    }


async def save_result(session, agency_id, geo_id, result: SandboxResult, retry_days: int,
                      decided_by: str = "discovery", now: Optional[datetime] = None):
    """Store a tested candidate; create (or update) its source when it earned one."""
    from app.models.discovery import DiscoveryCandidate  # noqa: PLC0415
    from app.models.source import Source  # noqa: PLC0415

    now = now or datetime.now(timezone.utc)
    c = result.candidate
    row = (await session.execute(select(DiscoveryCandidate).where(
        DiscoveryCandidate.agency_id == agency_id, DiscoveryCandidate.platform == c.platform,
        DiscoveryCandidate.external_id == c.external_id))).scalars().first()
    if row is None:
        row = DiscoveryCandidate(agency_id=agency_id, geo_location_id=geo_id,
                                 platform=c.platform, external_id=c.external_id)
        session.add(row)
    row.name, row.url = c.name, c.url
    row.rank_score, row.sandbox_score = c.rank_score, result.sandbox_score
    row.verdict, row.is_alive, row.decided_by = result.verdict, result.is_alive, decided_by
    row.tested_at = now
    row.retry_after = (now + timedelta(days=1 if result.retry_only else retry_days)
                       if result.verdict == "SANDBOX" else None)
    row.raw_meta = {**(c.meta or {}), "audience": c.audience, "reason": result.reason,
                    "samples": c.samples[:3]}

    fields = None if result.retry_only else source_fields(result)
    if fields and result.verdict in ("ACTIVATE", "SANDBOX"):
        source = await session.get(Source, row.source_id) if row.source_id else None
        if source is None:
            source = Source(agency_id=agency_id, geo_location_id=geo_id, **fields)
            session.add(source)
            await session.flush()
            row.source_id = source.id
        elif source.status in ("sandbox", "active"):
            # a re-test moves a discovery source; one the manager paused stays paused
            source.status = fields["status"]
            source.score, source.sandbox_score = fields["score"], fields["sandbox_score"]
    elif result.verdict == "REJECT" and row.source_id:
        source = await session.get(Source, row.source_id)
        if source is not None and source.discovered_by == "discovery" and source.status == "sandbox":
            source.status = "paused"
    return row


class DiscoveryScheduler:
    """Оркестратор: один город одного агентства за запуск."""

    def __init__(self, session, agency, geo, *, searchers=None, guard=None, clients=None, ai=None):
        self.session = session
        self.agency = agency
        self.geo = geo
        self.cfg = discovery_settings(agency)
        self.searchers = searchers if searchers is not None else all_searchers()
        self.guard = guard or RateLimitGuard(self.cfg.get("platform_budgets"))
        self._clients = clients
        self._ai = ai

    def competitor_names(self) -> list[str]:
        return competitor_names_of(self.agency)

    async def _search_all(self, kw, ctx, report: DiscoveryReport) -> list:
        active = [s for s in self.searchers
                  if s.state() != STUB and platform_enabled(self.cfg, s.platform)]
        for s in self.searchers:
            if s not in active:
                state = STUB if s.state() == STUB else "disabled"
                report.by_platform[s.platform] = {"state": state,
                                                  "why": getattr(s, "why_unavailable", "")}
        results = await asyncio.gather(
            *(asyncio.wait_for(s.search(kw, ctx), timeout=SEARCH_TIMEOUT) for s in active),
            return_exceptions=True)
        found = []
        for s, res in zip(active, results):
            if isinstance(res, BaseException):
                report.errors[s.platform] = f"{type(res).__name__}: {str(res)[:200]}"
                report.by_platform[s.platform] = {"state": "error", "found": 0}
                logger.warning("Searcher failed", platform=s.platform, error=str(res)[:200])
                continue
            report.by_platform[s.platform] = {"state": s.state(), "found": len(res)}
            found.extend(res)
        return found

    async def run(self) -> DiscoveryReport:
        started = time.monotonic()
        report = DiscoveryReport(agency_id=self.agency.id, city=self.geo.city_name)
        lock = redis_client()
        lock_key = RUN_LOCK.format(geo=self.geo.id)
        got = True
        try:
            got = bool(await lock.set(lock_key, "1", nx=True, ex=RUN_LOCK_TTL))
        except Exception as e:  # noqa: BLE001 - без Redis идём без замка
            logger.warning("Discovery run lock unavailable", error=str(e)[:120])
        if not got:
            await lock.aclose()
            report.errors["lock"] = "этот город уже ищется другим процессом"
            return report
        clients = self._clients or PlatformClients()
        try:
            kw = await KeywordBuilder(self.geo, self.competitor_names()).refresh()
            ctx = SearchContext(clients=clients, guard=self.guard, agency_id=self.agency.id,
                                geo_id=self.geo.id, city=self.geo.city_name, session=self.session)
            found = await self._search_all(kw, ctx, report)
            report.found = len(found)
            ranked = CandidateRanker(kw.niche_tags, kw.city_variations).rank(found)
            unique = await DuplicateFilter(self.session, self.agency.id).check(ranked)
            report.passed_dup = len(unique)
            allowed = (await self.guard.check(unique))[:int(self.cfg["max_new_sources_per_run"])]
            tester = SandboxTester(clients, self.guard, self.geo.city_name, self.agency.id,
                                   self.cfg["sandbox_score_activate"],
                                   self.cfg["sandbox_score_sandbox"], ai=self._ai)
            report.results = await tester.test_batch(allowed)
            report.tested = len(report.results)
            for r in report.results:
                await save_result(self.session, self.agency.id, self.geo.id, r,
                                  int(self.cfg["sandbox_retry_days"]))
                if r.verdict == "ACTIVATE":
                    report.activated += 1
                elif r.verdict == "SANDBOX":
                    report.sandboxed += 1
                else:
                    report.rejected += 1
            if ctx.competitors_found:
                self._remember_competitors(ctx.competitors_found)
        finally:
            if self._clients is None:
                await clients.close()
            try:
                await lock.delete(lock_key)
            except Exception:  # noqa: BLE001
                pass
            await lock.aclose()
        report.duration_s = round(time.monotonic() - started, 1)
        await self._persist_report(report)
        logger.info("Discovery run", agency_id=str(self.agency.id), city=self.geo.city_name,
                    found=report.found, passed_dup=report.passed_dup, tested=report.tested,
                    activated=report.activated, sandboxed=report.sandboxed,
                    rejected=report.rejected, duration_s=report.duration_s)
        return report

    def _remember_competitors(self, names: list[str]) -> None:
        settings = dict(self.agency.settings or {})
        known = list(settings.get(AUTO_COMPETITORS_KEY) or [])
        lower = {n.lower() for n in known}
        own = (self.agency.name or "").lower()
        for name in names:
            if name.lower() not in lower and name.lower() != own:
                known.append(name)
                lower.add(name.lower())
        settings[AUTO_COMPETITORS_KEY] = known[:MAX_COMPETITORS]
        self.agency.settings = settings

    async def _persist_report(self, report: DiscoveryReport) -> None:
        from app.models.discovery import DiscoveryLog  # noqa: PLC0415

        self.session.add(DiscoveryLog(
            agency_id=self.agency.id, geo_location_id=self.geo.id, city=report.city,
            found=report.found, passed_dup=report.passed_dup, tested=report.tested,
            activated=report.activated, sandboxed=report.sandboxed, rejected=report.rejected,
            by_platform=report.by_platform, errors=report.errors, duration_s=report.duration_s))
        await self.session.commit()


async def run_for_geo(geo_id, *, force: bool = False) -> Optional[DiscoveryReport]:
    """Run discovery for one city in its own DB session (Celery entry point)."""
    from app.database import async_session  # noqa: PLC0415
    from app.models.agency import Agency  # noqa: PLC0415
    from app.models.geo_location import GeoLocation  # noqa: PLC0415

    async with async_session() as session:
        geo = await session.get(GeoLocation, uuid.UUID(str(geo_id)))
        if geo is None:
            return None
        agency = await session.get(Agency, geo.agency_id)
        if agency is None:
            return None
        if not force and not discovery_settings(agency).get("enabled"):
            return None
        return await DiscoveryScheduler(session, agency, geo).run()


async def retry_due_candidates(now: Optional[datetime] = None) -> dict:
    """Re-test SANDBOX candidates whose retry_after has come (daily task)."""
    from app.database import async_session  # noqa: PLC0415
    from app.models.agency import Agency  # noqa: PLC0415
    from app.models.discovery import DiscoveryCandidate  # noqa: PLC0415
    from app.models.geo_location import GeoLocation  # noqa: PLC0415
    from app.services.discovery.types import SourceCandidate  # noqa: PLC0415

    now = now or datetime.now(timezone.utc)
    counts: dict[str, int] = {}
    async with async_session() as session:
        due = (await session.execute(select(DiscoveryCandidate).where(
            DiscoveryCandidate.verdict == "SANDBOX",
            DiscoveryCandidate.retry_after.is_not(None),
            DiscoveryCandidate.retry_after <= now,
        ).order_by(DiscoveryCandidate.retry_after).limit(50))).scalars().all()
        async with PlatformClients() as clients:
            for row in due:
                agency = await session.get(Agency, row.agency_id)
                geo = await session.get(GeoLocation, row.geo_location_id) if row.geo_location_id else None
                if agency is None or geo is None:
                    row.retry_after = None
                    continue
                cfg = discovery_settings(agency)
                meta = dict(row.raw_meta or {})
                cand = SourceCandidate(platform=row.platform, external_id=row.external_id,
                                       name=row.name or row.external_id, url=row.url or "",
                                       audience=int(meta.get("audience") or 0),
                                       samples=list(meta.get("samples") or []), meta=meta,
                                       rank_score=row.rank_score or 0.0)
                tester = SandboxTester(clients, RateLimitGuard(cfg.get("platform_budgets")),
                                       geo.city_name, agency.id, cfg["sandbox_score_activate"],
                                       cfg["sandbox_score_sandbox"])
                result = (await tester.test_batch([cand]))[0]
                await save_result(session, agency.id, geo.id, result, int(cfg["sandbox_retry_days"]),
                                  now=now)
                counts[result.verdict] = counts.get(result.verdict, 0) + 1
            await session.commit()
    return counts
