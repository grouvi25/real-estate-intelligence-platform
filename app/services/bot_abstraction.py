"""Bot abstraction layer: one interface for Telegram + MAX. TZ section 9.1.

Business logic calls bot_layer.send_message()/notify_manager() and never touches
platform specifics. Adding a platform means adding a private _send_<platform>.
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Optional

import httpx
import structlog
from pydantic import BaseModel

from app.config import config

logger = structlog.get_logger()

# The bot token sits in the Telegram API path, and httpx puts the failing URL in
# the exception text -- so every send failure wrote the token into the logs
# verbatim. Observed in production while testing the /start handler.
_TOKEN_IN_URL = re.compile(r"(https://api\.telegram\.org/bot)[^/\s]+")


def _redact(text: str) -> str:
    """Strip bot tokens out of anything headed for the logs."""
    redacted = _TOKEN_IN_URL.sub(r"\1***", text)
    for secret in (config.telegram_bot_token, config.max_bot_token):
        if secret and len(secret) > 6:
            redacted = redacted.replace(secret, "***")
    return redacted


class BotPlatform(str, Enum):
    TELEGRAM = "telegram"
    MAX = "max"


class BotButton(BaseModel):
    text: str
    callback_data: Optional[str] = None
    url: Optional[str] = None
    mini_app_url: Optional[str] = None


class BotMessage(BaseModel):
    text: str
    buttons: Optional[list[BotButton]] = None
    parse_mode: str = "HTML"


def _telegram_button(btn: BotButton) -> dict:
    """Map a BotButton to Telegram's inline keyboard shape.

    mini_app_url was part of the model from the start but never rendered, so a
    button that opens the Mini App could not actually be sent -- which is the one
    button the bot needs, since the Mini App is the whole interface.
    """
    if btn.mini_app_url:
        return {"text": btn.text, "web_app": {"url": btn.mini_app_url}}
    return {
        k: v
        for k, v in (("text", btn.text), ("url", btn.url), ("callback_data", btn.callback_data))
        if v is not None
    }


class BotAbstractionLayer:
    def __init__(self):
        self.http = httpx.AsyncClient(timeout=15.0)

    async def send_message(self, user_id: int, platform: BotPlatform, message: BotMessage) -> bool:
        try:
            if platform == BotPlatform.TELEGRAM:
                return await self._send_telegram(user_id, message)
            if platform == BotPlatform.MAX:
                return await self._send_max(user_id, message)
            logger.error("Unknown platform", platform=str(platform))
            return False
        except Exception as e:  # noqa: BLE001
            logger.error(
                "Failed to send message", platform=getattr(platform, "value", platform),
                user_id=user_id, error=_redact(str(e)),
            )
            return False

    async def _send_telegram(self, chat_id: int, message: BotMessage) -> bool:
        url = f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage"
        payload: dict = {
            "chat_id": chat_id,
            "text": message.text,
            "parse_mode": message.parse_mode,
            "disable_web_page_preview": True,
        }
        if message.buttons:
            payload["reply_markup"] = {
                "inline_keyboard": [
                    [_telegram_button(btn) for btn in message.buttons]
                ]
            }
        response = await self.http.post(url, json=payload)
        response.raise_for_status()
        return bool(response.json().get("ok", False))

    async def _send_max(self, user_id: int, message: BotMessage) -> bool:
        url = f"{config.max_base_url}/messages"
        headers = {"Authorization": f"Bearer {config.max_bot_token}"}
        payload: dict = {
            "user_id": user_id,
            "text": message.text,
            "parse_mode": message.parse_mode,
        }
        if message.buttons:
            payload["buttons"] = [
                {"text": b.text, "url": b.url} for b in message.buttons
            ]
        response = await self.http.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.status_code < 400

    async def notify_manager(self, manager_id: str, text: str) -> bool:
        """Send a notification to a manager on their preferred platform."""
        from app.database import async_session
        from app.models.manager import Manager

        async with async_session() as session:
            manager = await session.get(Manager, manager_id)
            if not manager or not manager.is_active:
                return False
            platform = BotPlatform(manager.preferred_platform)
            target_id = (
                manager.telegram_id if platform == BotPlatform.TELEGRAM else manager.max_user_id
            )
            if not target_id:
                logger.warning("Manager has no platform id", manager_id=manager_id, platform=platform.value)
                return False
            return await self.send_message(target_id, platform, BotMessage(text=text))

    async def close(self) -> None:
        await self.http.aclose()


# Singleton for the app lifetime.
bot_layer = BotAbstractionLayer()
