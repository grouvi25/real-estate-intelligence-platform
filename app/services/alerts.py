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
