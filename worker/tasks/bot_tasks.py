"""Celery tasks of the AI sales bot. ТЗ «AI-бот продажник» v1, разделы 6-7."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from celery import shared_task

from worker.async_runner import run_async

logger = structlog.get_logger()

REMIND_AFTER = timedelta(hours=24)


@shared_task(name="worker.tasks.bot_tasks.reply_to_signal")
def reply_to_signal(signal_id: str) -> dict:
    from app.services.bot_reply_engine import process_signal

    return run_async(process_signal(signal_id))


@shared_task(name="worker.tasks.bot_tasks.publish_public_reply")
def publish_public_reply(reply_id: str) -> dict:
    """Semi-auto: send after the delay unless a manager handled it meanwhile."""
    from app.services.bot_reply_engine import publish

    return run_async(publish(reply_id, by="bot"))


async def _reminders(now=None) -> int:
    """ТЗ 1.2: a buyer quiet for a day gets one reminder, then the bot is silent."""
    from sqlalchemy import select

    from app.database import async_session
    from app.models.agency import Agency
    from app.models.bot import BotConversation
    from app.prompts.bot_dm import REMINDER_TEXT
    from app.services.bot_conversation import _send

    now = now or datetime.now(timezone.utc)
    sent = 0
    async with async_session() as session:
        convs = (await session.execute(select(BotConversation).where(
            BotConversation.state == "qualifying", BotConversation.reminded_at.is_(None),
            BotConversation.last_user_msg_at < now - REMIND_AFTER,
        ))).scalars().all()
        for conv in convs:
            agency = await session.get(Agency, conv.agency_id)
            if agency is None or agency.bot_mode == "disabled":
                continue
            if await _send(agency, conv.user_id, REMINDER_TEXT):
                sent += 1
            conv.reminded_at = now
            conv.state = "silent"
        await session.commit()
    return sent


@shared_task(name="worker.tasks.bot_tasks.send_conversation_reminders")
def send_conversation_reminders() -> int:
    return run_async(_reminders())


async def _update_learning_pool() -> int:
    """ТЗ 7.1, weekly: what worked becomes an example.

    A pair «message -> our public reply» counts when the reply brought the
    person to a lead; it weighs more when the lead became a deal. These are the
    examples build_reply_prompt_with_examples feeds back to the model.
    """
    from sqlalchemy import select

    from app.database import async_session
    from app.models.bot import BotLearningPool, BotPublicReply
    from app.models.lead import Lead
    from app.models.signal import Signal

    added = 0
    async with async_session() as session:
        replies = (await session.execute(select(BotPublicReply).where(
            BotPublicReply.converted_to_lead.is_(True)))).scalars().all()
        for reply in replies:
            signal = await session.get(Signal, reply.signal_id)
            if signal is None:
                continue
            lead = (await session.execute(select(Lead).where(Lead.signal_id == signal.id))).scalars().first()
            outcome, weight = ("deal", 3.0) if lead is not None and lead.status == "deal" else ("lead_created", 1.5)
            pair = [{"user_message": (signal.raw_text or "")[:500],
                     "bot_reply": reply.reply_text.split("\nhttps://t.me/")[0][:500]}]
            existing = (await session.execute(select(BotLearningPool).where(
                BotLearningPool.agency_id == reply.agency_id,
                BotLearningPool.scenario == pair))).scalars().first()
            if existing is not None:
                existing.outcome, existing.weight = outcome, weight
                continue
            session.add(BotLearningPool(agency_id=reply.agency_id, tone_variant=reply.tone_variant,
                                        scenario=pair, outcome=outcome, weight=weight))
            added += 1
        await session.commit()
    logger.info("Bot learning pool updated", added=added)
    return added


@shared_task(name="worker.tasks.bot_tasks.update_bot_learning_pool")
def update_bot_learning_pool() -> int:
    return run_async(_update_learning_pool())
