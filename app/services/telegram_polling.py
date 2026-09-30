"""Telegram updates by long polling: the `bot` service in docker-compose.

A webhook needs Telegram to reach us, and from Yandex Cloud it did not:
getWebhookInfo kept reporting "Connection timed out" while the endpoint answered
everyone else. Polling goes out through the same SOCKS5 channel as the rest of
Telegram (TELEGRAM_PROXY_URL), so inbound reachability stops mattering. On a host
where webhooks work this still works too; the two must not run at once, which is
why the webhook is dropped on start.

This module ran on the production VM for weeks without ever being committed, while
docker-compose.yml referenced it -- a deploy onto a fresh machine would have left
the bot crash-looping. It is rebuilt here from what the compose file, the webhook
handler and the handoff notes say it did.

Every Telegram call is wrapped in asyncio.wait_for: through SOCKS the httpx
timeout does not fire on a stalled connection, and the loop would hang forever.

    python -m app.services.telegram_polling
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import structlog

from app.config import config

logger = structlog.get_logger()

POLL_TIMEOUT = 50  # seconds Telegram holds getUpdates open
CALL_SLACK = 15  # on top of it, before we give up on a stalled connection
MAX_BACKOFF = 60
ALLOWED_UPDATES = ["message", "edited_message", "callback_query"]
PLACEHOLDER_TOKENS = {"", "dev", "1:dev", "123:TEST"}


class TelegramPoller:
    def __init__(self, token: str, http=None):
        self.token = token
        self._http = http
        self.offset: Optional[int] = None

    @property
    def http(self):
        if self._http is None:
            from app.services.bot_abstraction import bot_layer  # noqa: PLC0415

            self._http = bot_layer.telegram_http
        return self._http

    def _url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.token}/{method}"

    async def call(self, method: str, payload: dict, timeout: float) -> Any:
        response = await asyncio.wait_for(
            self.http.post(self._url(method), json=payload, timeout=timeout), timeout=timeout + 5)
        body = response.json()
        if not body.get("ok"):
            raise RuntimeError(f"{method}: {body.get('description', 'not ok')}")
        return body.get("result")

    async def drop_webhook(self) -> None:
        """A set webhook makes getUpdates fail with 409; polling needs it gone.
        Pending updates are kept: they are messages people already sent."""
        await self.call("deleteWebhook", {"drop_pending_updates": False}, timeout=CALL_SLACK)
        logger.info("Telegram webhook removed, polling instead")

    async def fetch(self) -> list[dict]:
        payload: dict[str, Any] = {"timeout": POLL_TIMEOUT, "allowed_updates": ALLOWED_UPDATES}
        if self.offset is not None:
            payload["offset"] = self.offset
        return await self.call("getUpdates", payload, timeout=POLL_TIMEOUT + CALL_SLACK) or []

    async def handle(self, update: dict) -> None:
        """Same handling as the webhook route -- one place decides what /start does."""
        from app.routers.webhooks import handle_telegram_message  # noqa: PLC0415

        message = update.get("message") or update.get("edited_message")
        if message:
            await handle_telegram_message(message)

    async def poll_once(self) -> int:
        updates = await self.fetch()
        for update in updates:
            # Advance first: an update that breaks the handler must not be
            # fetched again forever (the webhook route answers 200 for the same reason).
            self.offset = int(update["update_id"]) + 1
            try:
                await self.handle(update)
            except Exception as e:  # noqa: BLE001
                logger.error("Telegram update handling failed",
                             update_id=update.get("update_id"), error=str(e)[:300])
        return len(updates)

    async def run(self, stop: Optional[asyncio.Event] = None) -> None:
        backoff = 1
        webhook_dropped = False
        while stop is None or not stop.is_set():
            try:
                if not webhook_dropped:
                    await self.drop_webhook()
                    webhook_dropped = True
                await self.poll_once()
                backoff = 1
            except Exception as e:  # noqa: BLE001 - the loop is the service
                from app.services.bot_abstraction import _redact  # noqa: PLC0415

                logger.warning("Telegram polling failed, retrying",
                               error=_redact(f"{type(e).__name__}: {e}")[:300], retry_in=backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF)


async def main() -> None:
    from app.logging_config import setup_logging  # noqa: PLC0415

    setup_logging()
    token = (config.telegram_bot_token or "").strip()
    if token in PLACEHOLDER_TOKENS:
        # Crash-looping the container would not make a token appear; idle instead
        # and say so once, so the stand without a bot still comes up clean.
        logger.warning("TELEGRAM_BOT_TOKEN is not set, Telegram polling is idle")
        await asyncio.Event().wait()
    logger.info("Telegram polling started", via_proxy=bool(config.telegram_proxy_url))
    await TelegramPoller(token).run()


if __name__ == "__main__":
    asyncio.run(main())
