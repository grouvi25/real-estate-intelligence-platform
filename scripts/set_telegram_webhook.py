"""Register (or inspect) the Telegram webhook. TZ 35.12.

`getWebhookInfo` returned an empty url on production: the bot could send
notifications but never received anything, so /start went unanswered.

    docker compose exec app python scripts/set_telegram_webhook.py          # show
    docker compose exec app python scripts/set_telegram_webhook.py --set    # set
    docker compose exec app python scripts/set_telegram_webhook.py --delete

The URL is derived from BASE_URL + the app's own route, so it cannot drift from
what the router actually serves.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app.config import config  # noqa: E402

WEBHOOK_PATH = "/api/webhooks/telegram"
ALLOWED_UPDATES = ["message", "edited_message", "callback_query"]


def webhook_url() -> str:
    return f"{config.base_url.rstrip('/')}{WEBHOOK_PATH}"


async def call(client: httpx.AsyncClient, method: str, **payload) -> dict:
    url = f"https://api.telegram.org/bot{config.telegram_bot_token}/{method}"
    res = await client.post(url, json=payload or None)
    return res.json()


def show(info: dict) -> None:
    r = info.get("result") or {}
    print(f"  url                  : {r.get('url') or '(not set)'}")
    print(f"  pending_update_count : {r.get('pending_update_count', 0)}")
    print(f"  has_custom_certificate: {r.get('has_custom_certificate')}")
    if r.get("last_error_message"):
        print(f"  last_error           : {r['last_error_message']}")
    if r.get("allowed_updates"):
        print(f"  allowed_updates      : {', '.join(r['allowed_updates'])}")


async def main() -> int:
    if not config.telegram_bot_token or config.telegram_bot_token == "dev":
        print("TELEGRAM_BOT_TOKEN is not configured.")
        return 1

    action = sys.argv[1] if len(sys.argv) > 1 else "--show"
    async with httpx.AsyncClient(timeout=20.0) as client:
        if action == "--set":
            if not config.telegram_webhook_secret:
                # Without it the endpoint accepts anything that reaches the URL.
                print("TELEGRAM_WEBHOOK_SECRET is not set — refusing to register "
                      "an unauthenticated webhook.")
                return 1
            if not config.base_url.startswith("https://"):
                print(f"BASE_URL must be https for Telegram webhooks: {config.base_url}")
                return 1

            res = await call(
                client, "setWebhook",
                url=webhook_url(),
                secret_token=config.telegram_webhook_secret,
                allowed_updates=ALLOWED_UPDATES,
                drop_pending_updates=True,
            )
            print(f"setWebhook -> {res.get('ok')} {res.get('description', '')}")
            if not res.get("ok"):
                return 1
        elif action == "--delete":
            res = await call(client, "deleteWebhook", drop_pending_updates=True)
            print(f"deleteWebhook -> {res.get('ok')} {res.get('description', '')}")

        print("\ngetWebhookInfo:")
        show(await call(client, "getWebhookInfo"))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
