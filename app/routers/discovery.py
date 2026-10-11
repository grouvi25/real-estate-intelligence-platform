"""Source discovery: what it found, what it did, how it is set up. ТЗ «Сигналы» v1.0, раздел 4.

Agency side (owner): candidates and the run log, manual activate/reject, settings.
Platform side (operator token): run now, forum seeds.

The ТЗ paths are /api/v1/discovery/*; REIP has no /v1 prefix anywhere, so they
live under /api/discovery/*.
"""
from __future__ import annotations

import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.database import get_session
from app.dependencies import (
    CurrentManager,
    get_current_manager,
    get_platform_operator,
    require_owner,
)
from app.exceptions import AppException, NotFoundError, ValidationError

logger = structlog.get_logger()
router = APIRouter()

VERDICTS = ("ACTIVATE", "SANDBOX", "REJECT")
VERDICT_RU = {"ACTIVATE": "Подключён", "SANDBOX": "Песочница", "REJECT": "Отклонён"}


def _candidate_dto(c) -> dict:
    meta = c.raw_meta or {}
    return {
        "id": str(c.id),
        "platform": c.platform,
        "external_id": c.external_id,
        "name": c.name,
        "url": c.url,
        "rank_score": c.rank_score,
        "sandbox_score": c.sandbox_score,
        "verdict": c.verdict,
        "verdict_label": VERDICT_RU.get(c.verdict or "", "Не проверен"),
        "is_alive": c.is_alive,
        "decided_by": c.decided_by,
        "reason": meta.get("reason") or "",
        "audience": meta.get("audience") or 0,
        "source_id": str(c.source_id) if c.source_id else None,
        "geo_location_id": str(c.geo_location_id) if c.geo_location_id else None,
        "discovered_at": c.discovered_at.isoformat() if c.discovered_at else None,
        "tested_at": c.tested_at.isoformat() if c.tested_at else None,
        "retry_after": c.retry_after.isoformat() if c.retry_after else None,
    }


def _log_dto(r) -> dict:
    return {
        "id": str(r.id), "run_at": r.run_at.isoformat() if r.run_at else None, "city": r.city,
        "found": r.found, "passed_dup": r.passed_dup, "tested": r.tested,
        "activated": r.activated, "sandboxed": r.sandboxed, "rejected": r.rejected,
        "by_platform": r.by_platform or {}, "errors": r.errors or {}, "duration_s": r.duration_s,
    }


async def _owned_candidate(session, current: CurrentManager, candidate_id: uuid.UUID):
    from app.models.discovery import DiscoveryCandidate  # noqa: PLC0415

    row = await session.get(DiscoveryCandidate, candidate_id)
    if row is None or str(row.agency_id) != current.agency_id:
        raise NotFoundError("Candidate", str(candidate_id))
    return row


@router.get("/candidates")
async def list_candidates(
    verdict: Optional[str] = Query(None, description="ACTIVATE | SANDBOX | REJECT"),
    platform: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """What discovery found for this agency, newest first."""
    from app.models.discovery import DiscoveryCandidate  # noqa: PLC0415

    await require_owner(session, current)
    stmt = select(DiscoveryCandidate).where(
        DiscoveryCandidate.agency_id == uuid.UUID(current.agency_id))
    if verdict:
        if verdict not in VERDICTS:
            raise ValidationError("verdict", f"недопустимый вердикт: {verdict}")
        stmt = stmt.where(DiscoveryCandidate.verdict == verdict)
    if platform:
        stmt = stmt.where(DiscoveryCandidate.platform == platform)
    rows = (await session.execute(stmt.order_by(
        DiscoveryCandidate.tested_at.desc().nullslast(),
        DiscoveryCandidate.discovered_at.desc()).limit(limit))).scalars().all()
    return {"candidates": [_candidate_dto(r) for r in rows], "count": len(rows)}


@router.post("/candidates/{candidate_id}/activate")
async def activate_candidate(
    candidate_id: uuid.UUID,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """Owner turns a candidate into an active source, whatever discovery decided."""
    from app.models.source import Source  # noqa: PLC0415
    from app.services.discovery.scheduler import source_fields  # noqa: PLC0415
    from app.services.discovery.types import SandboxResult, SourceCandidate  # noqa: PLC0415

    await require_owner(session, current)
    row = await _owned_candidate(session, current, candidate_id)
    source = await session.get(Source, row.source_id) if row.source_id else None
    if source is None:
        cand = SourceCandidate(platform=row.platform, external_id=row.external_id,
                               name=row.name or row.external_id, url=row.url or "",
                               meta=dict(row.raw_meta or {}), rank_score=row.rank_score or 0)
        fields = source_fields(SandboxResult(cand, row.sandbox_score or 0, bool(row.is_alive),
                                             "ACTIVATE"))
        if fields is None:
            raise AppException(400, "Эта находка не источник для сбора (например, карточка "
                                    "организации) — подключать нечего", "NOT_A_SOURCE")
        fields["discovered_by"] = "discovery"
        source = Source(agency_id=row.agency_id, geo_location_id=row.geo_location_id, **fields)
        session.add(source)
        await session.flush()
        row.source_id = source.id
    source.status = "active"
    source.consecutive_failures = 0
    row.verdict, row.decided_by, row.retry_after = "ACTIVATE", "manager", None
    await session.commit()
    logger.info("Discovery candidate activated by owner", candidate_id=str(candidate_id))
    return _candidate_dto(row)


@router.post("/candidates/{candidate_id}/reject")
async def reject_candidate(
    candidate_id: uuid.UUID,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """Owner rejects a candidate; a source discovery made from it is paused, not deleted."""
    from app.models.source import Source  # noqa: PLC0415

    await require_owner(session, current)
    row = await _owned_candidate(session, current, candidate_id)
    row.verdict, row.decided_by, row.retry_after = "REJECT", "manager", None
    if row.source_id:
        source = await session.get(Source, row.source_id)
        if source is not None and source.status in ("active", "sandbox"):
            source.status = "paused"
    await session.commit()
    logger.info("Discovery candidate rejected by owner", candidate_id=str(candidate_id))
    return _candidate_dto(row)


@router.get("/log")
async def discovery_log(
    limit: int = Query(20, ge=1, le=200),
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """History of discovery runs for this agency."""
    from app.models.discovery import DiscoveryLog  # noqa: PLC0415

    await require_owner(session, current)
    rows = (await session.execute(select(DiscoveryLog).where(
        DiscoveryLog.agency_id == uuid.UUID(current.agency_id)).order_by(
        DiscoveryLog.run_at.desc()).limit(limit))).scalars().all()
    return {"runs": [_log_dto(r) for r in rows]}


def _platforms() -> list[dict]:
    from app.services.discovery.searchers import all_searchers  # noqa: PLC0415

    return [{"platform": s.platform, "title": s.title, "state": s.state(),
             "why": s.why_unavailable if s.state() != "active" else ""}
            for s in all_searchers()]


@router.get("/config")
async def get_config(
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """Discovery settings of the agency plus what each platform can do right now."""
    from app.models.agency import Agency  # noqa: PLC0415
    from app.services.discovery.settings import (  # noqa: PLC0415
        AUTO_COMPETITORS_KEY,
        discovery_settings,
    )

    await require_owner(session, current)
    agency = await session.get(Agency, uuid.UUID(current.agency_id))
    return {"config": discovery_settings(agency), "platforms": _platforms(),
            "competitors_found": list((agency.settings or {}).get(AUTO_COMPETITORS_KEY) or [])}


@router.patch("/config")
async def patch_config(
    patch: dict,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """Partial update: {"enabled": false}, {"max_new_sources_per_run": 5},
    {"platform_budgets": {"youtube": {"enabled": false}}}."""
    from app.models.agency import Agency  # noqa: PLC0415
    from app.services.discovery.settings import apply_patch  # noqa: PLC0415

    await require_owner(session, current)
    agency = await session.get(Agency, uuid.UUID(current.agency_id))
    try:
        cfg = apply_patch(agency, patch)
    except ValueError as e:
        raise AppException(400, str(e), "VALIDATION_ERROR") from None
    await session.commit()
    return {"config": cfg, "platforms": _platforms()}


class RunRequest(BaseModel):
    geo_location_id: Optional[uuid.UUID] = None
    agency_id: Optional[uuid.UUID] = None


@router.post("/run")
async def run_now(
    req: RunRequest,
    operator_id: int = Depends(get_platform_operator),
    session=Depends(get_session),
):
    """Start discovery now (platform operator; debugging and tests). One city by
    geo_location_id, or every active city of agency_id."""
    from app.models.geo_location import GeoLocation  # noqa: PLC0415
    from worker.tasks.discovery import QUEUE, run_discovery_for_geo  # noqa: PLC0415

    if req.geo_location_id:
        geo_ids = [req.geo_location_id]
    elif req.agency_id:
        geo_ids = list((await session.execute(select(GeoLocation.id).where(
            GeoLocation.agency_id == req.agency_id,
            GeoLocation.is_active.is_(True)))).scalars().all())
    else:
        raise ValidationError("geo_location_id", "укажите город или агентство")
    if not geo_ids:
        raise AppException(404, "У агентства нет активных городов", "NO_GEO")
    for geo_id in geo_ids:
        run_discovery_for_geo.apply_async(args=[str(geo_id)], kwargs={"force": True}, queue=QUEUE)
    logger.info("Discovery started by operator", operator=operator_id, cities=len(geo_ids))
    return {"queued": [str(g) for g in geo_ids]}


class ForumSeedRequest(BaseModel):
    city: str
    domain: str
    description: Optional[str] = None
    active: bool = True


def _seed_dto(s) -> dict:
    return {"id": str(s.id), "city": s.city, "domain": s.domain,
            "description": s.description, "active": s.active}


@router.get("/forum-seeds")
async def list_forum_seeds(
    operator_id: int = Depends(get_platform_operator),
    session=Depends(get_session),
):
    from app.models.discovery import DiscoveryForumSeed  # noqa: PLC0415

    rows = (await session.execute(select(DiscoveryForumSeed).order_by(
        DiscoveryForumSeed.city, DiscoveryForumSeed.domain))).scalars().all()
    return {"seeds": [_seed_dto(r) for r in rows]}


@router.post("/forum-seeds", status_code=201)
async def add_forum_seed(
    req: ForumSeedRequest,
    operator_id: int = Depends(get_platform_operator),
    session=Depends(get_session),
):
    from app.models.discovery import DiscoveryForumSeed  # noqa: PLC0415

    domain = req.domain.strip().lower()
    for prefix in ("https://", "http://"):
        domain = domain.removeprefix(prefix)
    domain = domain.removeprefix("www.").split("/")[0]
    if not domain or "." not in domain or not req.city.strip():
        raise ValidationError("domain", "укажите город и домен форума, например forum.example.ru")
    existing = await session.scalar(select(DiscoveryForumSeed).where(
        DiscoveryForumSeed.domain == domain))
    if existing is not None:
        raise AppException(409, "Такой форум уже есть", "SEED_EXISTS")
    seed = DiscoveryForumSeed(city=req.city.strip(), domain=domain,
                              description=req.description, active=req.active)
    session.add(seed)
    await session.commit()
    return _seed_dto(seed)


@router.delete("/forum-seeds/{seed_id}")
async def delete_forum_seed(
    seed_id: uuid.UUID,
    operator_id: int = Depends(get_platform_operator),
    session=Depends(get_session),
):
    from app.models.discovery import DiscoveryForumSeed  # noqa: PLC0415

    seed = await session.get(DiscoveryForumSeed, seed_id)
    if seed is None:
        raise NotFoundError("ForumSeed", str(seed_id))
    await session.delete(seed)
    await session.commit()
    return {"deleted": True}
