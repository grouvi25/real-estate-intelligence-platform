"""Public-chat replies of the AI sales bot. ТЗ «AI-бот продажник» v1, разделы 1.1, 5.2, 7.2.

A hot signal gets a reply written by the model (tone, few-shot examples from
replies that led somewhere) and then, by the agency's mode:

- assist     -- the draft lands in the existing reply queue of the Mini App
                (signal.reply_draft, Signal Bus), a manager sends it or not;
- semi_auto  -- it is sent after N minutes unless a manager rejected it first;
- auto       -- it is sent at once.

Sending goes through the same Signal Bus path as a manager's reply, so the
outcome lands on the signal either way. A Telegram bot can only post to a chat
it is a member of, and the chats are read by a separate user account -- a
failure for that reason is recorded as such, not counted as sent.

The mode can never exceed what the agency's plan allows (subscription_plans.
bot_mode_allowed), and there is a daily ceiling per agency (bot_daily_reply_limit).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import select

from app.config import config

logger = structlog.get_logger()

MODES = ("disabled", "assist", "semi_auto", "auto")
TONES = ("expert", "friendly", "concise")
DAILY_KEY = "bot:replies:{agency_id}:{day}"


def effective_mode(agency, plan=None) -> str:
    """The agency's bot mode, capped by its plan (ТЗ «SaaS-слой», тарифы)."""
    mode = agency.bot_mode if agency.bot_mode in MODES else "disabled"
    if plan is not None and plan.bot_mode_allowed in MODES:
        return MODES[min(MODES.index(mode), MODES.index(plan.bot_mode_allowed))]
    return mode


def pick_tone(agency, now: Optional[datetime] = None) -> str:
    """ТЗ 7.2: a fixed tone, or rotation for the A/B test."""
    if agency.bot_tone_ab_test != "rotating":
        return agency.bot_tone_ab_test if agency.bot_tone_ab_test in TONES else "expert"
    return TONES[(now or datetime.now(timezone.utc)).hour % len(TONES)]


async def _daily(agency_id: str, increment: bool = False) -> int:
    """Replies sent today. Redis down = no ceiling, said in the log (ТЗ 9.3)."""
    import redis.asyncio as redis  # noqa: PLC0415

    key = DAILY_KEY.format(agency_id=agency_id, day=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    client = redis.from_url(config.redis_url, socket_connect_timeout=2, socket_timeout=2)
    try:
        if increment:
            value = await client.incr(key)
            await client.expire(key, 2 * 86400)
            return int(value)
        return int(await client.get(key) or 0)
    except Exception as e:  # noqa: BLE001
        logger.warning("Bot daily counter unavailable, no ceiling applied", error=str(e)[:120])
        return 0
    finally:
        await client.aclose()


async def _examples(session, agency_id) -> list[dict]:
    from app.models.bot import BotLearningPool  # noqa: PLC0415

    rows = (await session.execute(select(BotLearningPool).where(
        BotLearningPool.agency_id == agency_id,
        BotLearningPool.outcome.in_(("lead_created", "deal", "escalated_converted")),
    ).order_by(BotLearningPool.weight.desc(), BotLearningPool.created_at.desc()).limit(10)))\
        .scalars().all()
    out: list[dict] = []
    for row in rows:
        out.extend(e for e in (row.scenario or []) if isinstance(e, dict))
    return out[:3]


def dm_link(agency, reply_id: uuid.UUID) -> Optional[str]:
    """Deep link into the bot's DM that remembers which reply brought the person."""
    bot = agency.telegram_bot_username or config.telegram_bot_username
    if not bot or bot in ("dev_bot", "test_bot"):
        return None
    return f"https://t.me/{bot}?start=r_{reply_id.hex[:12]}"


async def generate_reply(session, agency, signal, tone: str) -> str:
    from app.prompts.reply_generator import USER_PROMPT_REPLY, build_reply_prompt_with_examples  # noqa: PLC0415
    from app.services.ai_service import AIService, safe_ai_parse  # noqa: PLC0415

    system = build_reply_prompt_with_examples(await _examples(session, agency.id), tone)
    ai = AIService()
    try:
        res = await ai.complete(system, USER_PROMPT_REPLY.format(
            agency_name=agency.name,
            city=signal.geo_location.city_name if signal.geo_location else agency.base_city,
            original_message=(signal.raw_text or "")[:800],
            intent_analysis={k: (signal.ai_analysis or {}).get(k) for k in
                             ("segment", "urgency", "budget_max", "location_interest", "property_type")},
            lead_magnet_url="",
        ), "reply_generator", agency_id=str(agency.id))
    finally:
        await ai.close()
    return str(safe_ai_parse(res, {"reply_text": ""}).get("reply_text") or "").strip()


async def process_signal(signal_id: str) -> dict:
    """Entry point from scoring: should the bot answer this signal, and how."""
    from app.database import async_session  # noqa: PLC0415
    from app.models.agency import Agency  # noqa: PLC0415
    from app.models.billing import SubscriptionPlan  # noqa: PLC0415
    from app.models.bot import BotPublicReply  # noqa: PLC0415
    from app.models.signal import Signal  # noqa: PLC0415

    async with async_session() as session:
        signal = await session.get(Signal, uuid.UUID(str(signal_id)))
        if signal is None or signal.status == "rejected":
            return {"skipped": "no_signal"}
        agency = await session.get(Agency, signal.agency_id)
        plan = await session.get(SubscriptionPlan, agency.subscription_plan) if agency else None
        mode = effective_mode(agency, plan) if agency else "disabled"
        if mode == "disabled":
            return {"skipped": "disabled"}
        if (signal.intent_score or 0) < (agency.bot_reply_threshold or 60):
            return {"skipped": "below_threshold"}
        if await session.scalar(select(BotPublicReply.id).where(BotPublicReply.signal_id == signal.id)):
            return {"skipped": "already_replied"}
        if await _daily(str(agency.id)) >= (agency.bot_daily_reply_limit or 50):
            logger.info("Bot daily reply limit reached", agency_id=str(agency.id))
            return {"skipped": "daily_limit"}

        tone = pick_tone(agency)
        try:
            text = await generate_reply(session, agency, signal, tone)
        except Exception as e:  # noqa: BLE001 - no AI, no reply; the signal is still there
            logger.warning("Bot reply not generated", signal_id=str(signal.id), error=str(e)[:200])
            return {"skipped": "ai_failed"}
        if not text:
            return {"skipped": "empty_reply"}

        reply = BotPublicReply(id=uuid.uuid4(), agency_id=agency.id, signal_id=signal.id,
                               reply_text=text, tone_variant=tone, mode=mode, status="draft")
        link = dm_link(agency, reply.id)
        if link:
            reply.reply_text = f"{text}\n{link}"
        signal.reply_draft = reply.reply_text
        signal.reply_status = "pending"
        signal.reply_channel = signal.reply_channel or "telegram"
        if mode == "semi_auto":
            reply.status = "scheduled"
            reply.scheduled_for = datetime.now(timezone.utc) + timedelta(
                minutes=agency.bot_semi_auto_delay or 5)
        session.add(reply)
        await session.commit()
        reply_id = str(reply.id)

    if mode == "assist":
        await _tell_managers(agency, f"ИИ подготовил ответ в чат — он в очереди ответов:\n\n{text[:500]}")
    elif mode == "semi_auto":
        from worker.tasks.bot_tasks import publish_public_reply  # noqa: PLC0415

        publish_public_reply.apply_async(args=[reply_id], countdown=(agency.bot_semi_auto_delay or 5) * 60)
        await _tell_managers(agency, f"ИИ ответит в чат через {agency.bot_semi_auto_delay or 5} мин, "
                                     f"если вы не отклоните ответ в очереди:\n\n{text[:500]}")
    else:
        await publish(reply_id, by="bot")
    return {"reply_id": reply_id, "mode": mode}


async def _tell_managers(agency, text: str) -> None:
    from app.database import async_session  # noqa: PLC0415
    from app.models.manager import Manager  # noqa: PLC0415
    from app.services.bot_abstraction import bot_layer  # noqa: PLC0415

    async with async_session() as session:
        ids = (await session.execute(select(Manager.id).where(
            Manager.agency_id == agency.id, Manager.is_active.is_(True),
            Manager.role.in_(("owner", "admin"))))).scalars().all()
    for manager_id in ids:
        await bot_layer.notify_manager(str(manager_id), text)


async def publish(reply_id: str, *, by: str = "bot", manager_id: Optional[str] = None) -> dict:
    """Send a reply to its chat through Signal Bus. Only a draft or a scheduled
    reply is sent -- a rejected or already sent one is left alone."""
    from app.database import async_session  # noqa: PLC0415
    from app.models.bot import BotPublicReply  # noqa: PLC0415
    from app.models.signal import Signal  # noqa: PLC0415
    from app.services.signal_bus import send_signal_reply  # noqa: PLC0415

    async with async_session() as session:
        reply = await session.get(BotPublicReply, uuid.UUID(str(reply_id)))
        if reply is None or reply.status not in ("draft", "scheduled"):
            return {"sent": False, "reason": "not_pending"}
        signal = await session.get(Signal, reply.signal_id)
        if signal is None or signal.reply_status not in ("pending", "draft"):
            # The manager got there first: sent it from the queue (replied) or
            # dismissed / escalated the signal. Either way the bot stays quiet.
            if signal is not None and signal.reply_status == "replied":
                reply.status, reply.sent_by, reply.sent_at = "sent", "manager", signal.replied_at
            else:
                reply.status = "rejected"
            await session.commit()
            return {"sent": False, "reason": "signal_handled"}
        signal.reply_draft = reply.reply_text
        result = await send_signal_reply(session, signal, manager_id)
        if result.get("sent"):
            reply.status, reply.sent_at, reply.sent_by = "sent", datetime.now(timezone.utc), by
            if manager_id:
                reply.approved_by = uuid.UUID(str(manager_id))
            await _daily(str(reply.agency_id), increment=True)
        else:
            reply.status = "failed"
            reply.fail_reason = str(result.get("reason") or result.get("error")
                                    or "бот не может написать в этот чат (скорее всего, не состоит в нём)")[:300]
        await session.commit()
        logger.info("Bot public reply", reply_id=reply_id, status=reply.status, by=by)
        return {"sent": reply.status == "sent", "status": reply.status, "reason": reply.fail_reason}


async def reject(session, reply) -> None:
    reply.status = "rejected"
    await session.commit()
