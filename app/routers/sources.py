"""Monitoring sources router. TZ section 30 (screen `/admin/sources`), 15.

Source Discovery finds and AI-scores Telegram chats and writes them here, and the
collector reads whatever is `active`/`sandbox` -- but there was no way to see what
the engine picked, promote a sandbox source, pause a bad one or add a chat by
hand. The first live run made that concrete: discovery activated a long-term
rental chat, which then produced 22 renter messages, and the only way to stop it
was an UPDATE against the database.

Manager-scoped: the agency always comes from the JWT, never from client input.
"""
from __future__ import annotations

import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import func, select

from app.database import get_session
from app.dependencies import CurrentManager, get_current_manager
from app.exceptions import AppException, NotFoundError, ValidationError
from app.models.geo_location import GeoLocation
from app.models.signal import Signal
from app.models.source import Source

logger = structlog.get_logger()
router = APIRouter()

# migrations/001_init.sql + 008_status_extensions.sql
VALID_STATUSES = {"sandbox", "active", "paused", "blocked", "dead"}
SOURCE_TYPES = {"telegram_chat", "telegram_channel", "vk_group", "youtube", "rss", "forum"}
MAX_PAGE = 500


class CreateSourceRequest(BaseModel):
    source_url: str
    source_name: Optional[str] = None
    source_type: str = "telegram_chat"
    geo_location_id: Optional[uuid.UUID] = None
    status: str = "sandbox"


class UpdateSourceRequest(BaseModel):
    status: Optional[str] = None
    source_name: Optional[str] = None
    geo_location_id: Optional[uuid.UUID] = None
    score: Optional[int] = None


def _telegram_username(url: str) -> Optional[str]:
    if "t.me/" in url:
        return url.split("t.me/")[-1].strip("/") or None
    return None


def _source_dto(s: Source, signals: int = 0, city: Optional[str] = None) -> dict:
    return {
        "id": str(s.id),
        "source_name": s.source_name,
        "source_url": s.source_url,
        "source_type": s.source_type,
        "external_id": s.external_id,
        "status": s.status,
        "score": s.score,
        "signals_per_day": s.signals_per_day,
        "signals_total": signals,
        "auto_found": bool(s.auto_found),
        "geo_location_id": str(s.geo_location_id) if s.geo_location_id else None,
        "city_name": city,
        "last_checked_at": s.last_checked_at.isoformat() if s.last_checked_at else None,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


@router.get("")
async def list_sources(
    status: str = "all",
    limit: int = 100,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """List monitoring sources with their signal counts, best score first."""
    limit = min(max(limit, 1), MAX_PAGE)
    if status != "all" and status not in VALID_STATUSES:
        raise ValidationError("status", f"недопустимый статус: {status}")

    stmt = select(Source).where(Source.agency_id == uuid.UUID(current.agency_id))
    if status != "all":
        stmt = stmt.where(Source.status == status)
    sources = (await session.execute(
        stmt.order_by(Source.score.desc(), Source.created_at.desc()).limit(limit)
    )).scalars().all()

    counts = dict(
        (await session.execute(
            select(Signal.source_id, func.count(Signal.id)).where(
                Signal.agency_id == uuid.UUID(current.agency_id)
            ).group_by(Signal.source_id)
        )).all()
    )
    geo_ids = {s.geo_location_id for s in sources if s.geo_location_id}
    cities: dict[uuid.UUID, str] = {}
    if geo_ids:
        rows = (await session.execute(
            select(GeoLocation).where(GeoLocation.id.in_(geo_ids))
        )).scalars().all()
        cities = {g.id: g.city_name for g in rows}

    return {
        "sources": [
            _source_dto(s, counts.get(s.id, 0), cities.get(s.geo_location_id))
            for s in sources
        ],
        "count": len(sources),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_source(
    req: CreateSourceRequest,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """Add a source by hand (e.g. a chat the agency already knows)."""
    if req.source_type not in SOURCE_TYPES:
        raise ValidationError("source_type", f"недопустимый тип: {req.source_type}")
    if req.status not in VALID_STATUSES:
        raise ValidationError("status", f"недопустимый статус: {req.status}")

    url = req.source_url.strip()
    if not url:
        raise ValidationError("source_url", "укажите ссылку на источник")
    if url.startswith("@"):
        url = f"https://t.me/{url.lstrip('@')}"

    agency_id = uuid.UUID(current.agency_id)
    existing = await session.scalar(
        select(Source.id).where(Source.agency_id == agency_id, Source.source_url == url)
    )
    if existing:
        raise ValidationError("source_url", "такой источник уже добавлен")

    source = Source(
        agency_id=agency_id,
        geo_location_id=req.geo_location_id,
        source_type=req.source_type,
        source_url=url,
        source_name=req.source_name or _telegram_username(url) or url,
        # The collector resolves Telegram sources by username; store it so a
        # manually added source behaves like an auto-found one.
        external_id=_telegram_username(url),
        status=req.status,
        auto_found=False,
    )
    session.add(source)
    await session.commit()
    logger.info("Source added manually", source_id=str(source.id), url=url)
    return _source_dto(source)


@router.patch("/{source_id}")
async def update_source(
    source_id: uuid.UUID,
    req: UpdateSourceRequest,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """Promote, pause or re-label a source."""
    source = await session.get(Source, source_id)
    if source is None or str(source.agency_id) != current.agency_id:
        raise NotFoundError("Source", str(source_id))

    if req.status is not None:
        if req.status not in VALID_STATUSES:
            raise ValidationError("status", f"недопустимый статус: {req.status}")
        source.status = req.status
    if req.source_name is not None:
        source.source_name = req.source_name
    if req.geo_location_id is not None:
        source.geo_location_id = req.geo_location_id
    if req.score is not None:
        if not 0 <= req.score <= 100:
            raise ValidationError("score", "оценка должна быть от 0 до 100")
        source.score = req.score

    await session.commit()
    logger.info("Source updated", source_id=str(source_id), status=source.status)
    return _source_dto(source)


@router.delete("/{source_id}")
async def delete_source(
    source_id: uuid.UUID,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """Delete a source that never produced anything; otherwise block and hint.

    Signals reference the source, and losing that link would break attribution
    (v_signal_to_outcome) and Source ROI, so a productive source is paused
    instead of removed.
    """
    source = await session.get(Source, source_id)
    if source is None or str(source.agency_id) != current.agency_id:
        raise NotFoundError("Source", str(source_id))

    signals = await session.scalar(
        select(func.count()).select_from(Signal).where(Signal.source_id == source_id)
    )
    if signals:
        raise AppException(
            status_code=409,
            detail=f"У источника {signals} сигналов — удаление разорвёт атрибуцию, отключите его вместо удаления",
            code="SOURCE_HAS_SIGNALS",
        )

    await session.delete(source)
    await session.commit()
    logger.info("Source deleted", source_id=str(source_id))
    return {"deleted": True, "id": str(source_id)}
