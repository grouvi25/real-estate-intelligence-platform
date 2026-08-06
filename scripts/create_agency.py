"""Create an agency with its first owner, and print the invite link.

There was no way to do this at all: no endpoint, no script. The one agency in
production had been created by hand with an INSERT, and a second one could not be
onboarded -- while geo protection and partner referrals, the whole point of the
platform, only mean anything between several agencies.

It stays a script rather than an endpoint on purpose: creating an agency is an
operator action, and an endpoint would need an admin authentication story of its
own to avoid being the very hole this closes.

    docker compose exec app python scripts/create_agency.py \
        --name "Агентство Геленджик" --city Геленджик --owner-telegram-id 7503416516

The owner's Telegram id is what @userinfobot answers with. Managers are added
afterwards through the printed link, not through this script.
"""
from __future__ import annotations

import argparse
import asyncio
import secrets
import sys


async def main() -> int:
    parser = argparse.ArgumentParser(description="Завести агентство и владельца")
    parser.add_argument("--name", required=True, help="Название агентства")
    parser.add_argument("--city", required=True, help="Основной город")
    parser.add_argument("--owner-telegram-id", type=int, required=True,
                        help="Telegram id владельца (спросите у @userinfobot)")
    parser.add_argument("--owner-name", default="Владелец")
    args = parser.parse_args()

    from sqlalchemy import select

    from app.database import async_session, run_migrations
    from app.models.agency import Agency
    from app.models.manager import Manager
    from app.routers.auth import invite_link

    await run_migrations()

    async with async_session() as session:
        existing = await session.scalar(
            select(Manager).where(Manager.telegram_id == args.owner_telegram_id)
        )
        if existing is not None:
            print(f"Этот Telegram id уже привязан к агентству {existing.agency_id}.")
            print("Один аккаунт не может быть владельцем двух агентств.")
            return 1

        agency = Agency(name=args.name, base_city=args.city,
                        invite_token=secrets.token_hex(16))
        session.add(agency)
        await session.flush()

        session.add(Manager(
            agency_id=agency.id,
            name=args.owner_name,
            telegram_id=args.owner_telegram_id,
            preferred_platform="telegram",
            role="owner",
            is_active=True,
        ))
        await session.commit()

        print(f"Агентство: {agency.name} ({agency.id})")
        print(f"Владелец:  telegram_id={args.owner_telegram_id}")
        print()
        print("Ссылка для менеджеров (её же владелец видит в Профиле):")
        print(f"  {invite_link(agency.invite_token)}")
        print()
        print("Дальше: владелец открывает бота, добавляет город и каталог объектов.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
