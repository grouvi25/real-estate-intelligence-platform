"""AI sales bot settings, its replies and its numbers. ТЗ «AI-бот продажник» 7.4, 8.

The reply queue itself is the Signal Bus queue that already exists (Mini App →
Очередь): the bot's drafts land there as reply drafts, and a manager sends or
dismisses them with the buttons already on it. Here: the owner's settings, the
list of what the bot did, and the effectiveness numbers.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.database import get_session
from app.dependencies import CurrentManager, get_current_manager, require_owner
from app.exceptions import AppException

router = APIRouter()


class BotSettings(BaseModel):
    bot_mode: Optional[Literal["disabled", "assist", "semi_auto", "auto"]] = None
    bot_reply_threshold: Optional[int] = Field(default=None, ge=0, le=100)
    bot_daily_reply_limit: Optional[int] = Field(default=None, ge=1, le=500)
    bot_semi_auto_delay: Optional[int] = Field(default=None, ge=1, le=60)
    bot_tone_ab_test: Optional[Literal["expert", "friendly", "concise", "rotating"]] = None


async def _agency_and_plan(session, current: CurrentManager):
    from app.models.agency import Agency
    from app.models.billing import SubscriptionPlan

    agency = await session.get(Agency, uuid.UUID(current.agency_id))
    if agency is None:
        raise AppException(404, "Агентство не найдено", "NOT_FOUND")
    return agency, await session.get(SubscriptionPlan, agency.subscription_plan)


def _dto(agency, plan) -> dict:
    from app.services.bot_reply_engine import effective_mode

    return {
        "bot_mode": agency.bot_mode, "effective_mode": effective_mode(agency, plan),
        "max_mode": plan.bot_mode_allowed if plan is not None else "auto",
        "bot_reply_threshold": agency.bot_reply_threshold,
        "bot_daily_reply_limit": agency.bot_daily_reply_limit,
        "bot_semi_auto_delay": agency.bot_semi_auto_delay,
        "bot_tone_ab_test": agency.bot_tone_ab_test,
        "bot_username": agency.telegram_bot_username,
    }


@router.get("/settings")
async def get_settings(current: CurrentManager = Depends(get_current_manager), session=Depends(get_session)):
    return _dto(*await _agency_and_plan(session, current))


@router.patch("/settings")
async def update_settings(req: BotSettings, current: CurrentManager = Depends(get_current_manager),
                          session=Depends(get_session)):
    """Owner only. A mode above the plan is refused, not silently lowered: the
    owner should know why «Auto» is not what they got."""
    from app.services.bot_reply_engine import MODES

    await require_owner(session, current)
    agency, plan = await _agency_and_plan(session, current)
    if req.bot_mode and plan is not None and plan.bot_mode_allowed in MODES \
            and MODES.index(req.bot_mode) > MODES.index(plan.bot_mode_allowed):
        raise AppException(403, f"Режим недоступен на тарифе «{plan.name}»", "PLAN_LIMIT_BOT_MODE")
    for field, value in req.model_dump(exclude_none=True).items():
        setattr(agency, field, value)
    await session.commit()
    return _dto(agency, plan)


@router.get("/replies")
async def replies(limit: int = Query(20, ge=1, le=100), current: CurrentManager = Depends(get_current_manager),
                  session=Depends(get_session)):
    from app.models.bot import BotPublicReply

    rows = (await session.execute(select(BotPublicReply).where(
        BotPublicReply.agency_id == uuid.UUID(current.agency_id)
    ).order_by(BotPublicReply.created_at.desc()).limit(limit))).scalars().all()
    return {"replies": [{
        "id": str(r.id), "signal_id": str(r.signal_id), "text": r.reply_text, "status": r.status,
        "mode": r.mode, "tone": r.tone_variant, "fail_reason": r.fail_reason,
        "got_response": r.got_response, "converted": r.converted_to_lead,
        "created_at": r.created_at.isoformat(),
    } for r in rows]}


@router.get("/performance")
async def performance(days: int = Query(30, ge=1, le=365), current: CurrentManager = Depends(get_current_manager),
                      session=Depends(get_session)):
    """ТЗ 7.4. The agency comes from the token, not a query parameter: the ТЗ
    version took agency_id from the URL and would show anyone's numbers."""
    from app.models.bot import BotConversation, BotPublicReply

    agency_id = uuid.UUID(current.agency_id)
    since = datetime.now(timezone.utc) - timedelta(days=days)

    async def count(model, *where):
        return await session.scalar(select(func.count(model.id)).where(
            model.agency_id == agency_id, model.created_at >= since, *where)) or 0

    sent = await count(BotPublicReply, BotPublicReply.status == "sent")
    answered = await count(BotPublicReply, BotPublicReply.status == "sent", BotPublicReply.got_response.is_(True))
    failed = await count(BotPublicReply, BotPublicReply.status == "failed")
    dms = await count(BotConversation)
    leads = await count(BotConversation, BotConversation.state == "qualified")
    return {
        "period_days": days, "public_replies_sent": sent, "public_replies_failed": failed,
        "got_response_count": answered, "response_rate_pct": round(answered / sent * 100, 1) if sent else 0.0,
        "dm_conversations_started": dms, "leads_created_by_bot": leads,
        "dm_to_lead_conversion_pct": round(leads / dms * 100, 1) if dms else 0.0,
    }
