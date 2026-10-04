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
            logger.warning(
                "WEBHOOK SECRET NOT CONFIGURED - accepting all requests (dev mode only). "
                "Set TELEGRAM_WEBHOOK_SECRET / MAX_WEBHOOK_SECRET before production deploy.",
                platform=platform,
                node_env=config.node_env,
            )
            return
        logger.error("Webhook secret is not configured in production", platform=platform)
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


async def handle_telegram_callback(callback: dict[str, Any], agency_id: Optional[str] = None) -> None:
    """Inline button presses: the consent buttons of the sales bot. The press is
    always acknowledged, or Telegram keeps the button spinning."""
    from app.services.bot_abstraction import bot_layer  # noqa: PLC0415
    from app.services.bot_conversation import handle_callback  # noqa: PLC0415

    try:
        await handle_callback(callback, agency_id)
    finally:
        token, _ = await _agency_bot(agency_id)
        try:
            await bot_layer.telegram_http.post(
                f"https://api.telegram.org/bot{token or config.telegram_bot_token}/answerCallbackQuery",
                json={"callback_query_id": callback.get("id")})
        except Exception:  # noqa: BLE001
            pass


async def _agency_bot(agency_id: Optional[str]):
    """(token, welcome text) of an agency's own bot, or (None, None)."""
    if not agency_id:
        return None, None
    import uuid  # noqa: PLC0415

    from app.database import async_session  # noqa: PLC0415
    from app.models.agency import Agency  # noqa: PLC0415

    async with async_session() as session:
        agency = await session.get(Agency, uuid.UUID(str(agency_id)))
    if agency is None:
        return None, None
    return agency.telegram_bot_token, (agency.welcome_message or "").strip() or None


async def handle_telegram_message(message: dict[str, Any],
                                  agency_id: Optional[str] = None) -> Optional[str]:
    """Reply to a bot command. Returns the command handled, or None.

    ``agency_id``: the update came to that agency's own bot (SaaS layer), so the
    answer goes out through it, with the agency's welcome text if it set one.
    """
    from app.services.bot_abstraction import BotButton, BotMessage, BotPlatform, bot_layer

    chat_id = (message.get("chat") or {}).get("id")
    text = (message.get("text") or "").strip()
    # A buyer talking to the AI sales bot (ТЗ «AI-бот продажник»): handled
    # there, and managers and invitations fall through to the cabinet below.
    try:
        from app.services.bot_conversation import handle_message as buyer_message  # noqa: PLC0415

        if await buyer_message(message, agency_id):
            return "buyer"
    except Exception as e:  # noqa: BLE001 - the cabinet must still answer /start
        logger.error("Buyer conversation failed", error=str(e)[:200])
    if not chat_id or not text.startswith("/"):
        return None

    bot_token, welcome = await _agency_bot(agency_id)
    command = text.split()[0].split("@")[0]
    if command == "/start":
        payload = start_payload(text)
        await bot_layer.send_message(
            chat_id,
            BotPlatform.TELEGRAM,
            BotMessage(
                text=welcome or WELCOME_TEXT,
                buttons=[BotButton(text="Открыть кабинет", mini_app_url=mini_app_url(payload))],
            ),
            bot_token,
        )
        logger.info("Telegram /start handled", chat_id=chat_id, payload=payload, agency_id=agency_id)
        return command

    await bot_layer.send_message(chat_id, BotPlatform.TELEGRAM, BotMessage(text=UNKNOWN_TEXT), bot_token)
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
        elif update.get("callback_query"):
            await handle_telegram_callback(update["callback_query"])
    except Exception as e:  # noqa: BLE001 - never bounce an update back to Telegram
        logger.error("Telegram update handling failed", error=str(e))

    return {"ok": True}


@router.post("/tg/{agency_id}")
async def telegram_webhook_agency(agency_id: str, request: Request):
    """ТЗ «SaaS-слой» 4.2: updates of an agency's own bot, when bots run on
    webhooks (TELEGRAM_UPDATES_MODE=webhook). The per-agency secret is required:
    without it anyone who guessed the URL could speak for the agency's bot."""
    import uuid  # noqa: PLC0415

    from app.database import async_session  # noqa: PLC0415
    from app.models.agency import Agency  # noqa: PLC0415

    try:
        agency_uuid = uuid.UUID(agency_id)
    except ValueError:
        raise ForbiddenError("Unknown agency bot") from None
    async with async_session() as session:
        agency = await session.get(Agency, agency_uuid)
    if agency is None or not agency.telegram_webhook_secret:
        raise ForbiddenError("Unknown agency bot")
    _require_secret(request.headers.get(TELEGRAM_SECRET_HEADER),
                    agency.telegram_webhook_secret, "telegram")
    try:
        update = await request.json()
    except Exception:  # noqa: BLE001
        update = {}
    try:
        message = update.get("message") or update.get("edited_message")
        if message:
            await handle_telegram_message(message, agency_id=str(agency.id))
        elif update.get("callback_query"):
            await handle_telegram_callback(update["callback_query"], agency_id=str(agency.id))
    except Exception as e:  # noqa: BLE001 - never bounce an update back to Telegram
        logger.error("Agency bot update handling failed", agency_id=agency_id, error=str(e)[:200])
    return {"ok": True}


def sales_webhook_secret() -> str:
    """Secret for the sales bot's webhook, derived from SECRET_KEY: nothing to add
    to .env, and it changes whenever the app secret does."""
    import hashlib  # noqa: PLC0415
    import hmac  # noqa: PLC0415

    return hmac.new(config.secret_key.encode(), b"sales-bot-webhook", hashlib.sha256).hexdigest()


@router.post("/sales")
async def sales_bot_webhook(request: Request):
    """ТЗ «SaaS-слой» 5.4: the platform's sales bot, when bots run on webhooks.
    The ТЗ version accepted anything; operator commands arrive here, so the
    secret is required."""
    _require_secret(request.headers.get(TELEGRAM_SECRET_HEADER), sales_webhook_secret(), "telegram")
    try:
        update = await request.json()
    except Exception:  # noqa: BLE001
        update = {}
    try:
        from app.services.sales_bot import handle_update  # noqa: PLC0415

        await handle_update(update)
    except Exception as e:  # noqa: BLE001
        logger.error("Sales bot update handling failed", error=str(e)[:200])
    return {"ok": True}


@router.post("/yookassa")
async def yookassa_webhook(request: Request):
    """ТЗ «SaaS-слой» 5.6. The body is only a hint: the payment is fetched back
    from ЮKassa before anything counts (app/services/yookassa.py). Always 200 --
    ЮKassa retries anything else for a day."""
    from app.database import async_session  # noqa: PLC0415
    from app.services import yookassa  # noqa: PLC0415

    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return {"ok": True}
    try:
        async with async_session() as session:
            paid = await yookassa.handle_notification(session, body)
        if paid:
            from app.services.sales_bot import notify_operators  # noqa: PLC0415

            await notify_operators(f"Оплата получена по заявке {paid[:8]}.\n"
                                   f"Создать агентство: /create_{paid[:8]} [токен бота агентства]")
    except Exception as e:  # noqa: BLE001
        logger.error("ЮKassa notification failed", error=str(e)[:200])
    return {"ok": True}


async def handle_max_event(update: dict[str, Any]) -> Optional[str]:
    """Reply to a MAX bot event. Returns the update_type handled, or None.

    MAX events are shaped `update_type` + `message.{sender,recipient,body}`, so
    the sender id and text sit in different places than Telegram's.
    """
    from app.services.bot_abstraction import BotButton, BotMessage, BotPlatform, bot_layer

    event_type = update.get("update_type")
    if event_type == "message_callback":
        return event_type if await handle_max_callback(update) else None
    if event_type not in ("message_created", "bot_started"):
        return None

    message = update.get("message") or {}
    sender = message.get("sender") or update.get("user") or {}
    user_id = sender.get("user_id") or update.get("user_id")
    text = ((message.get("body") or {}).get("text") or "").strip()
    if not user_id:
        return None

    # A buyer talking to the AI sales bot in MAX (ТЗ «AI-бот продажник»: MAX
    # through the same bot layer). bot_started carries the deep link payload.
    start_text = text or ("/start " + str(update.get("payload"))
                          if event_type == "bot_started" and update.get("payload") else "/start")
    try:
        from app.services.bot_conversation import handle_message as buyer_message  # noqa: PLC0415

        normalized = {"chat": {"id": int(user_id), "type": "private"}, "text": start_text,
                      "from": {"id": int(user_id), "username": sender.get("username"),
                               "first_name": sender.get("name") or sender.get("first_name")}}
        if await buyer_message(normalized, None, platform="max"):
            return "buyer"
    except Exception as e:  # noqa: BLE001 - the cabinet must still answer /start
        logger.error("MAX buyer conversation failed", error=str(e)[:200])

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


async def handle_max_callback(update: dict[str, Any]) -> bool:
    """A button press in MAX (the consent buttons). Always acknowledged: MAX,
    like Telegram, keeps a pressed button waiting until it is answered."""
    from app.services.bot_abstraction import bot_layer  # noqa: PLC0415
    from app.services.bot_conversation import handle_callback  # noqa: PLC0415

    callback = update.get("callback") or {}
    user_id = (callback.get("user") or update.get("user") or {}).get("user_id")
    if not callback.get("payload") or not user_id:
        return False  # not a press we sent
    try:
        return await handle_callback({"data": callback.get("payload"), "from": {"id": user_id}}, None,
                                     platform="max")
    finally:
        if callback.get("callback_id") and config.max_bot_token:
            try:
                await bot_layer.http.post(
                    f"{config.max_base_url.rstrip('/')}/answers",
                    params={"callback_id": callback["callback_id"]},
                    headers={"Authorization": config.max_bot_token},
                    json={"notification": "Принято"})
            except Exception:  # noqa: BLE001
                pass


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
