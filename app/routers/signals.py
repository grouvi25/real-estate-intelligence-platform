"""Signals router. TZ section 14.1.

- GET  /api/signals                     list + filter (geo, status, urgency, min score)
- POST /api/signals/{id}/create-lead    qualify signal -> lead (152-FZ consent) + matching
- POST /api/signals/{id}/generate-reply ecological public reply via AI

Fixes vs. TZ: matching is enqueued via a real Celery task (run_matching_for_lead),
not asyncio.create_task(...).delay(); datetime imports added; SYSTEM_PROMPT_REPLY
imported from reply_generator (its real module). Endpoints use plain defaults so
they are directly callable (not just via the HTTP layer).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends
from fastapi import status as http_status
from pydantic import BaseModel
from sqlalchemy import select

from app.config import config
from app.database import get_session
from app.dependencies import CurrentManager, get_current_manager
from app.exceptions import NotFoundError
from app.models.lead import Lead
from app.models.signal import Signal
from app.models.task import Task

logger = structlog.get_logger()
router = APIRouter()

MAX_PAGE = 200


class CreateLeadRequest(BaseModel):
    consent_text: str
    consent_ip: Optional[str] = None
    consent_user_agent: Optional[str] = None
    purchase_goal: str = "own"


class ReplyDraftRequest(BaseModel):
    reply_draft: str
    reply_channel: Optional[str] = None


REPLY_QUEUE_STATUSES = ("draft", "pending")


def _signal_dto(s: Signal) -> dict:
    """Shared shape for the list and the single-signal endpoints."""
    return {
        "id": str(s.id),
        "raw_text": s.raw_text,
        "intent_score": s.intent_score,
        "segment": s.segment,
        "urgency": s.urgency,
        "status": s.status,
        "geo_location_id": str(s.geo_location_id) if s.geo_location_id else None,
        "created_at": s.created_at.isoformat(),
    }


@router.get("")
async def list_signals(
    geo_id: Optional[uuid.UUID] = None,
    status: Optional[str] = None,
    urgency: Optional[str] = None,
    min_intent_score: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    limit = min(max(limit, 1), MAX_PAGE)
    offset = max(offset, 0)

    stmt = select(Signal).where(Signal.agency_id == uuid.UUID(current.agency_id))
    if geo_id is not None:
        stmt = stmt.where(Signal.geo_location_id == geo_id)
    if status is not None:
        stmt = stmt.where(Signal.status == status)
    if urgency is not None:
        stmt = stmt.where(Signal.urgency == urgency)
    if min_intent_score is not None:
        stmt = stmt.where(Signal.intent_score >= min_intent_score)
    stmt = stmt.order_by(Signal.created_at.desc()).limit(limit).offset(offset)

    rows = (await session.execute(stmt)).scalars().all()
    return {"count": len(rows), "signals": [_signal_dto(s) for s in rows]}


@router.post("/{signal_id}/create-lead", status_code=http_status.HTTP_201_CREATED)
async def create_lead_from_signal(
    signal_id: uuid.UUID,
    req: CreateLeadRequest,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    signal = await session.get(Signal, signal_id)
    if signal is None or str(signal.agency_id) != current.agency_id:
        raise NotFoundError("Signal", str(signal_id))

    # Idempotency: a signal qualifies into at most one lead. If it was already
    # qualified, return the existing lead instead of creating a duplicate.
    existing = (
        await session.execute(select(Lead).where(Lead.signal_id == signal.id))
    ).scalars().first()
    if existing is not None:
        return {"lead_id": str(existing.id), "tasks_created": 0,
                "matching_queued": False, "already_exists": True}

    ai = signal.ai_analysis or {}
    lead = Lead(
        agency_id=signal.agency_id,
        geo_location_id=signal.geo_location_id,
        signal_id=signal.id,
        source_signal_id=signal.id,
        source_type="signal",
        source_platform="telegram",
        segment=signal.segment or ai.get("segment"),
        intent_score=signal.intent_score,
        budget_min=signal.budget_min if signal.budget_min is not None else ai.get("budget_min"),
        budget_max=signal.budget_max if signal.budget_max is not None else ai.get("budget_max"),
        purchase_goal=req.purchase_goal,
        urgency=signal.urgency,
        status="new",
        consent_given=True,
        consent_given_at=datetime.now(timezone.utc),
        consent_text=req.consent_text,
        consent_version=config.consent_version,
        consent_ip=req.consent_ip,
        consent_user_agent=req.consent_user_agent,
    )
    # Carry the author's display name from the signal so the lead isn't nameless.
    if signal.author_display_name:
        lead.name = signal.author_display_name
    session.add(lead)
    await session.flush()

    session.add(
        Task(
            agency_id=lead.agency_id,
            lead_id=lead.id,
            task_type="contact",
            title="Первый контакт по сигналу",
            due_at=datetime.now(timezone.utc) + timedelta(hours=4),
            status="pending",
        )
    )
    signal.status = "qualified"
    await session.commit()

    # Matching runs off the request path. A broker hiccup must not fail lead
    # creation (the lead is already committed); log and continue.
    matching_queued = True
    try:
        from worker.tasks.matching_tasks import run_matching_for_lead

        run_matching_for_lead.delay(str(lead.id))
    except Exception as exc:  # noqa: BLE001
        matching_queued = False
        logger.error("Failed to enqueue matching for lead", lead_id=str(lead.id), error=str(exc))

    return {"lead_id": str(lead.id), "tasks_created": 1,
            "matching_queued": matching_queued, "already_exists": False}


@router.post("/{signal_id}/generate-reply")
async def generate_chat_reply(
    signal_id: uuid.UUID,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    signal = await session.get(Signal, signal_id)
    if signal is None or str(signal.agency_id) != current.agency_id:
        raise NotFoundError("Signal", str(signal_id))

    from app.prompts.reply_generator import SYSTEM_PROMPT_REPLY
    from app.services.ai_service import AIService, safe_ai_parse

    city = signal.geo_location.city_name if signal.geo_location else ""
    ai = AIService()
    try:
        prompt = f"Город: {city}\nСообщение: {signal.raw_text}"
        res = await ai.complete(
            SYSTEM_PROMPT_REPLY, prompt, "reply_generator", agency_id=str(signal.agency_id)
        )
    finally:
        await ai.close()
    return {"reply": safe_ai_parse(res, {"reply_text": "Ошибка генерации ответа"})}


# --- Signal Bus reply workflow (addendum) ----------------------------------


@router.get("/queue")
async def signal_reply_queue(
    limit: int = 50,
    offset: int = 0,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """Signals awaiting a reply (draft/pending), hottest first."""
    limit = min(max(limit, 1), MAX_PAGE)
    offset = max(offset, 0)
    stmt = (
        select(Signal)
        .where(Signal.agency_id == uuid.UUID(current.agency_id),
               Signal.reply_status.in_(REPLY_QUEUE_STATUSES))
        .order_by(Signal.intent_score.desc().nullslast(), Signal.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return {
        "count": len(rows),
        "signals": [
            {
                "id": str(s.id),
                "raw_text": s.raw_text,
                "intent_score": s.intent_score,
                "segment": s.segment,
                "origin_system": s.origin_system,
                "reply_channel": s.reply_channel,
                "reply_status": s.reply_status,
                "reply_draft": s.reply_draft,
                "created_at": s.created_at.isoformat(),
            }
            for s in rows
        ],
    }


@router.patch("/{signal_id}/reply-draft")
async def set_reply_draft(
    signal_id: uuid.UUID,
    req: ReplyDraftRequest,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """Save/update a reply draft for a signal (status -> draft)."""
    signal = await session.get(Signal, signal_id)
    if signal is None or str(signal.agency_id) != current.agency_id:
        raise NotFoundError("Signal", str(signal_id))
    signal.reply_draft = req.reply_draft
    if req.reply_channel is not None:
        signal.reply_channel = req.reply_channel
    signal.reply_status = "draft"
    await session.commit()
    return {"id": str(signal.id), "reply_status": signal.reply_status}


@router.post("/{signal_id}/send-reply")
async def send_reply(
    signal_id: uuid.UUID,
    manager_id: Optional[str] = None,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """Deliver the saved reply draft on the originating channel."""
    signal = await session.get(Signal, signal_id)
    if signal is None or str(signal.agency_id) != current.agency_id:
        raise NotFoundError("Signal", str(signal_id))

    from app.services.signal_bus import send_signal_reply

    result = await send_signal_reply(session, signal, manager_id=manager_id or current.manager_id)
    return {"id": str(signal.id), "reply_status": signal.reply_status, "result": result}


# Registered last on purpose: a UUID path param would reject "/queue" with a 422
# before FastAPI could reach the literal route, so it must come after it.
@router.get("/{signal_id}")
async def get_signal(
    signal_id: uuid.UUID,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """Fetch one signal. The Mini App used to pull the whole list and search it."""
    signal = await session.get(Signal, signal_id)
    if signal is None or str(signal.agency_id) != current.agency_id:
        raise NotFoundError("Signal", str(signal_id))
    return _signal_dto(signal)
