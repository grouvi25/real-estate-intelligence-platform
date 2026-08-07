"""Critical alerts to Telegram. TZ section 24.2.

Fired from: middleware on 5xx, Celery on failures, AI service when the daily
budget crosses 90%. Best-effort: never raises to the caller.
"""
from __future__ import annotations

import structlog

from app.config import config

logger = structlog.get_logger()


async def send_critical_alert(message: str) -> bool:
    """Send a critical alert to the admin Telegram chat. Returns False if unsent."""
    if not config.admin_telegram_id:
        logger.warning("ADMIN_TELEGRAM_ID not set; critical alert not delivered", alert=message)
        return False

    from app.services.bot_abstraction import BotMessage, BotPlatform, bot_layer

    return await bot_layer.send_message(
        user_id=config.admin_telegram_id,
        platform=BotPlatform.TELEGRAM,
        message=BotMessage(text=f"🚨 CRITICAL ALERT\n{message}", parse_mode="HTML"),
    )


async def notify_owner_escalation(session, signal, reason: str | None = None) -> bool:
    """Tell the agency's owner that a signal was handed upward.

    An escalation nobody hears about is just a signal that stopped moving, which
    is what the queue already had too much of.
    """
    from sqlalchemy import select

    from app.models.manager import Manager
    from app.services.bot_abstraction import bot_layer

    owner = (await session.execute(
        select(Manager).where(
            Manager.agency_id == signal.agency_id,
            Manager.role == "owner",
            Manager.is_active.is_(True),
        ).limit(1)
    )).scalars().first()
    if owner is None:
        logger.info("Escalation has no owner to notify", signal_id=str(signal.id))
        return False

    quote = (signal.raw_text or "")[:180]
    text = (f"⚠️ Сигнал передан вам\n\n«{quote}»\n\n"
            f"Оценка: {signal.intent_score if signal.intent_score is not None else '—'}/100")
    if reason:
        text += f"\nПричина: {reason}"

    try:
        return bool(await bot_layer.notify_manager(owner.id, text))
    except Exception as e:  # noqa: BLE001 - a failed notification must not undo the escalation
        logger.warning("Escalation notice failed", signal_id=str(signal.id), error=str(e))
        return False
