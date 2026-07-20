"""Platform webhooks. TZ section 31 (webhook security).

Telegram delivers updates with the ``X-Telegram-Bot-Api-Secret-Token`` header set
via setWebhook. We verify it against TELEGRAM_WEBHOOK_SECRET before processing.
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Request

from app.config import config
from app.exceptions import ForbiddenError

logger = structlog.get_logger()
router = APIRouter()

TELEGRAM_SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"


@router.post("/telegram")
async def telegram_webhook(request: Request):
    secret = request.headers.get(TELEGRAM_SECRET_HEADER)
    if config.telegram_webhook_secret and secret != config.telegram_webhook_secret:
        logger.warning("Telegram webhook secret mismatch")
        raise ForbiddenError("Invalid webhook secret")

    try:
        update = await request.json()
    except Exception:  # noqa: BLE001
        update = {}
    logger.info("Telegram update received", update_id=update.get("update_id"))
    # Update routing (aiogram dispatcher) is wired with the bot layer separately.
    return {"ok": True}


@router.post("/max")
async def max_webhook(request: Request):
    try:
        update = await request.json()
    except Exception:  # noqa: BLE001
        update = {}
    logger.info("MAX update received", keys=list(update.keys()))
    return {"ok": True}
