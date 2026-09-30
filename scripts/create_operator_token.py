"""Make someone a platform operator and print their API token. ТЗ «SaaS-слой» 6.2.

    docker compose exec app python scripts/create_operator_token.py 7503416516 --name "Михаил"

The operator is recorded in platform_operators (that is also what lets them use
the operator commands in the sales bot) and gets a JWT for /api/operator/*,
valid for --days (30 by default). Deactivating the row revokes every token of
theirs at once; there is nothing else to rotate.
"""
from __future__ import annotations

import argparse
import asyncio
import sys


async def main() -> int:
    parser = argparse.ArgumentParser(description="Оператор платформы REIP")
    parser.add_argument("telegram_id", type=int, help="Telegram id (его подскажет @userinfobot)")
    parser.add_argument("--name", default=None, help="Как подписывать оператора")
    parser.add_argument("--days", type=int, default=30, help="Срок жизни токена, дней")
    args = parser.parse_args()

    from sqlalchemy import select

    from app.database import async_session, engine
    from app.dependencies import create_operator_token
    from app.models.billing import PlatformOperator

    try:
        async with async_session() as session:
            op = (await session.execute(select(PlatformOperator).where(
                PlatformOperator.telegram_id == args.telegram_id))).scalar_one_or_none()
            if op is None:
                op = PlatformOperator(telegram_id=args.telegram_id, display_name=args.name)
                session.add(op)
            op.is_active = True
            if args.name:
                op.display_name = args.name
            await session.commit()
    finally:
        await engine.dispose()
    print(create_operator_token(args.telegram_id, days=args.days))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
