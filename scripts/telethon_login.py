"""One-off interactive Telethon login for the collector account. TZ section 15.

The collector reads public chats as a regular Telegram account (userbot), which
needs a session file created by an interactive login: Telegram sends a code, and
the account owner types it in. That login happens exactly once — afterwards the
session file in TELETHON_SESSION_NAME is reused by the worker.

Run it attached to a TTY, on the server, so the session lands on the mounted
volume:

    docker compose exec app python scripts/telethon_login.py

The script never stores the phone, code, or 2FA password: it forwards them
straight to Telethon, which writes only the resulting session token.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.collectors import telethon_sessions  # noqa: E402
from app.config import config  # noqa: E402


async def main() -> int:
    if not (config.telethon_api_id and config.telethon_api_hash):
        print("TELETHON_API_ID / TELETHON_API_HASH are not set in .env — nothing to log in with.")
        return 1

    try:
        from app.collectors.telegram_collector import build_client
    except ImportError:
        print("Telethon is not installed in this image (pip install telethon).")
        return 1

    # Каким аккаунтом входим, решает аргумент: без него — основной. Резервные
    # места очереди (TELETHON_SESSIONS) заполняются именно так, поэтому имя
    # обязано быть выбираемым, а не жёстко взятым из основной настройки.
    session = sys.argv[1] if len(sys.argv) > 1 else config.telethon_session_name
    known = telethon_sessions.sessions()
    if session not in known:
        print(f"ВНИМАНИЕ: {session} нет в очереди TELETHON_SESSIONS ({', '.join(known)}).")
        print("Сессия создастся, но сбор её не увидит, пока имя не в очереди.")
        print()
    session_dir = Path(session).parent
    if str(session_dir) not in ("", "."):
        session_dir.mkdir(parents=True, exist_ok=True)

    print(f"Session file: {session}.session")
    print(f"api_id: {config.telethon_api_id}")
    if config.telethon_dc_port:
        print(f"MTProto port: {config.telethon_dc_port} (pinned via TELETHON_DC_PORT)")
    print("\nTelegram will ask for the phone number of the COLLECTOR account,")
    print("then for the login code, and for the 2FA password if you have one.\n")

    # Same connection settings as the collector, so a session created here works
    # unchanged in the worker.
    client = build_client(session)
    # start() prompts on stdin for phone / code / password as needed.
    # Телефон из настроек — это номер основного аккаунта. Для любого другого
    # спрашиваем, иначе Telethon молча отправит код не туда.
    #
    # Спрашивать надо именно приглашением: start(phone=None) не переспрашивает,
    # а падает с "No phone number or bot token provided" — по умолчанию там
    # стоит функция ввода, и подменять её на None нельзя.
    phone = config.telethon_phone if session == config.telethon_session_name else None
    if phone:
        await client.start(phone=phone)
    else:
        await client.start(phone=lambda: input("Номер телефона аккаунта (+7...): ").strip())

    me = await client.get_me()
    username = f"@{me.username}" if me.username else "(no username)"
    print(f"\nLogged in as: {me.first_name or ''} {username} (id={me.id})")

    dialogs = 0
    async for _ in client.iter_dialogs(limit=200):
        dialogs += 1
    print(f"Visible dialogs: {dialogs}")

    await client.disconnect()
    print("\nDone. The worker will pick this session up on its next run.")
    print("Restart the worker to be sure:  docker compose restart worker")
    revived = await telethon_sessions.revive(session)
    if revived:
        print(f"Пометка «выбыл» с {session} снята — аккаунт снова в очереди.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
