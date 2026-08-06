"""Platform webhooks. TZ sections 31 (webhook security) and 35.12 (go-live).

Telegram delivers updates with the ``X-Telegram-Bot-Api-Secret-Token`` header set
via setWebhook; it is verified against TELEGRAM_WEBHOOK_SECRET before anything
else happens.

The handler used to log the update and drop it, so a manager who opened the bot
and typed /start got silence -- the only way into the Mini App was a link someone
sent by hand. /start now answers with the Mini App button and carries the deeplink
payload through as the campaign, which is what fills utm_campaign on a lead
created in that session (TZ 32.6 / 35.7).

Handlers never raise: Telegram retries any non-2xx delivery, so a bug here would
turn into a retry storm. Failures are logged and answered with 200.
"""
from __future__ import annotations

from typing import Any, Optional
from urllib.parse import quote

import structlog
from fastapi import APIRouter, Request

from app.config import config
from app.exceptions import ForbiddenError

logger = structlog.get_logger()
router = APIRouter()

TELEGRAM_SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"
MAX_SECRET_HEADER = "X-Max-Bot-Api-Secret"


def _require_secret(received: Optional[str], expected: Optional[str], platform: str) -> None:
    """Reject an update unless it carries the configured shared secret.

    An unset secret used to mean "skip the check", so the MAX endpoint accepted
    anything that reached the URL -- TZ 35.2 asks for 403. Outside development a
    missing secret is a misconfiguration, not permission to trust the caller:
    refusing is the safe reading, and it is the same choice already made for MAX
    initData and for registering the Telegram webhook.
    """
    if not expected:
        if config.node_env == "development":
            return
        logger.warning("Webhook secret is not configured; refusing", platform=platform)
        raise ForbiddenError("Webhook secret is not configured")
    if received != expected:
        logger.warning("Webhook secret mismatch", platform=platform)
        raise ForbiddenError("Invalid webhook secret")

WELCOME_TEXT = (
    "Это рабочий кабинет агентства.\n\n"
    "Здесь видно сигналы от людей, которые ищут жильё; тут же вы работаете "
    "с лидами и получаете задачи по ним.\n\n"
    "Нажмите кнопку ниже, чтобы открыть."
)
UNKNOWN_TEXT = "Я понимаю команду /start — нажмите её, чтобы открыть кабинет."


def mini_app_url(start_param: Optional[str] = None) -> str:
    """Mini App URL, carrying the deeplink payload as a UTM campaign."""
    base = f"{config.base_url.rstrip('/')}/mini-app/"
    if not start_param:
        return base
    return (
        f"{base}?utm_source=telegram_bot&utm_medium=bot_deeplink"
        f"&utm_campaign={quote(start_param, safe='')}"
    )


def start_payload(text: str) -> Optional[str]:
    """Payload of "/start <payload>" (i.e. t.me/<bot>?start=<payload>)."""
    parts = (text or "").strip().split(maxsplit=1)
    if not parts or parts[0].split("@")[0] != "/start":
        return None
    return parts[1].strip() or None if len(parts) > 1 else None


async def handle_telegram_message(message: dict[str, Any]) -> Optional[str]:
    """Reply to a bot command. Returns the command handled, or None."""
    from app.services.bot_abstraction import BotButton, BotMessage, BotPlatform, bot_layer

    chat_id = (message.get("chat") or {}).get("id")
    text = (message.get("text") or "").strip()
    if not chat_id or not text.startswith("/"):
        return None

    command = text.split()[0].split("@")[0]
    if command == "/start":
        payload = start_payload(text)
        await bot_layer.send_message(
            chat_id,
            BotPlatform.TELEGRAM,
            BotMessage(
                text=WELCOME_TEXT,
                buttons=[BotButton(text="Открыть кабинет", mini_app_url=mini_app_url(payload))],
            ),
        )
        logger.info("Telegram /start handled", chat_id=chat_id, payload=payload)
        return command

    await bot_layer.send_message(chat_id, BotPlatform.TELEGRAM, BotMessage(text=UNKNOWN_TEXT))
    logger.info("Telegram unknown command", chat_id=chat_id, command=command)
    return command


@router.post("/telegram")
async def telegram_webhook(request: Request):
    _require_secret(request.headers.get(TELEGRAM_SECRET_HEADER),
                    config.telegram_webhook_secret, "telegram")

    try:
        update = await request.json()
    except Exception:  # noqa: BLE001
        update = {}
    logger.info("Telegram update received", update_id=update.get("update_id"))

    try:
        message = update.get("message") or update.get("edited_message")
        if message:
            await handle_telegram_message(message)
    except Exception as e:  # noqa: BLE001 - never bounce an update back to Telegram
        logger.error("Telegram update handling failed", error=str(e))

    return {"ok": True}


async def handle_max_event(update: dict[str, Any]) -> Optional[str]:
    """Reply to a MAX bot event. Returns the update_type handled, or None.

    MAX events are shaped `update_type` + `message.{sender,recipient,body}`, so
    the sender id and text sit in different places than Telegram's.
    """
    from app.services.bot_abstraction import BotButton, BotMessage, BotPlatform, bot_layer

    event_type = update.get("update_type")
    if event_type not in ("message_created", "bot_started"):
        return None

    message = update.get("message") or {}
    user_id = (message.get("sender") or {}).get("user_id") or update.get("user_id")
    text = ((message.get("body") or {}).get("text") or "").strip()
    if not user_id:
        return None

    # bot_started has no text; treat it as /start.
    if event_type == "bot_started" or text.split()[0:1] == ["/start"]:
        payload = start_payload(text) if text else None
        await bot_layer.send_message(
            int(user_id),
            BotPlatform.MAX,
            BotMessage(
                text=WELCOME_TEXT,
                buttons=[BotButton(text="Открыть кабинет", mini_app_url=mini_app_url(payload))],
            ),
        )
        logger.info("MAX start handled", user_id=user_id, payload=payload)
        return event_type

    if text.startswith("/"):
        await bot_layer.send_message(int(user_id), BotPlatform.MAX, BotMessage(text=UNKNOWN_TEXT))
        return event_type
    return None


@router.post("/max")
async def max_webhook(request: Request):
    """MAX echoes the secret given at subscription time; it is not an HMAC.

    The endpoint used to accept anything that reached the URL, so a stranger
    could feed the bot arbitrary events.
    """
    _require_secret(request.headers.get(MAX_SECRET_HEADER),
                    config.max_webhook_secret, "max")

    try:
        update = await request.json()
    except Exception:  # noqa: BLE001
        update = {}
    logger.info("MAX update received", update_type=update.get("update_type"))

    try:
        await handle_max_event(update)
    except Exception as e:  # noqa: BLE001 - never bounce an update back to MAX
        logger.error("MAX update handling failed", error=str(e))

    return {"ok": True}
