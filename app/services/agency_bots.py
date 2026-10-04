"""Each agency's own Telegram bot. ТЗ «SaaS-слой» v1, раздел 4.

The token is checked with getMe before it is stored (a typo would otherwise sit
there silently until the first manager got no answer), kept encrypted, and one
bot can belong to one agency only. How its updates arrive follows
TELEGRAM_UPDATES_MODE: in "webhook" mode Telegram is told the agency's URL and
secret here; in "polling" mode the `bot` service picks new bots up by itself.
"""
from __future__ import annotations

import asyncio
import secrets
from typing import Optional

import structlog

from app.config import config

logger = structlog.get_logger()

TELEGRAM_TIMEOUT = 20


class AgencyBotError(Exception):
    """The token or the bot cannot be used; the message says why, in Russian."""


async def _telegram(token: str, method: str, payload: Optional[dict] = None) -> dict:
    from app.services.bot_abstraction import _redact, bot_layer  # noqa: PLC0415

    url = f"https://api.telegram.org/bot{token}/{method}"
    try:
        resp = await asyncio.wait_for(
            bot_layer.telegram_http.post(url, json=payload or {}), timeout=TELEGRAM_TIMEOUT)
        body = resp.json()
    except Exception as e:  # noqa: BLE001
        logger.warning("Telegram call failed", method=method, error=_redact(str(e))[:200])
        raise AgencyBotError("Telegram не отвечает, попробуйте позже") from None
    if not body.get("ok"):
        raise AgencyBotError(f"Telegram отказал: {body.get('description', 'неизвестная ошибка')}")
    return body.get("result") or {}


def webhook_url(agency_id: str) -> str:
    return f"{config.base_url.rstrip('/')}/api/webhooks/tg/{agency_id}"


async def attach_bot(session, agency, token: str) -> str:
    """Validate ``token`` and make it the agency's bot. Returns the @username."""
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.agency import Agency  # noqa: PLC0415

    token = (token or "").strip()
    if ":" not in token:
        raise AgencyBotError("Это не похоже на токен бота: его выдаёт @BotFather")
    if token == config.telegram_bot_token:
        raise AgencyBotError("Это бот самой платформы, у агентства должен быть свой")
    me = await _telegram(token, "getMe")
    if not me.get("is_bot") or not me.get("username"):
        raise AgencyBotError("Telegram не узнал в этом токене бота")
    username = me["username"]

    others = (await session.execute(
        select(Agency).where(Agency.id != agency.id,
                             Agency._telegram_bot_token_encrypted.is_not(None))
    )).scalars().all()
    if any(o.telegram_bot_token == token or
           (o.telegram_bot_username or "").lower() == username.lower() for o in others):
        raise AgencyBotError(f"Бот @{username} уже подключён к другому агентству")

    agency.telegram_bot_token = token
    agency.telegram_bot_username = username
    agency.telegram_webhook_secret = agency.telegram_webhook_secret or secrets.token_urlsafe(32)
    await session.commit()

    if config.telegram_updates_mode == "webhook":
        await _telegram(token, "setWebhook", {
            "url": webhook_url(str(agency.id)),
            "secret_token": agency.telegram_webhook_secret,
            "allowed_updates": ["message", "callback_query"],
        })
    logger.info("Agency bot attached", agency_id=str(agency.id), bot=username,
                mode=config.telegram_updates_mode)
    return username


async def detach_bot(session, agency) -> None:
    """The agency goes back to the platform bot. The old bot's webhook is
    dropped so it stops calling a URL that no longer answers for it."""
    token = agency.telegram_bot_token
    agency.telegram_bot_token = None
    agency.telegram_bot_username = None
    await session.commit()
    if token and config.telegram_updates_mode == "webhook":
        try:
            await _telegram(token, "deleteWebhook", {})
        except AgencyBotError:
            pass
