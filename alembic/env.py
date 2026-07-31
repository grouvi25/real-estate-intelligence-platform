"""Alembic environment. TZ 35.1.

The project applies schema through `migrations/*.sql` with an idempotent runner
(app.database.run_migrations), which is what production and the 22 database test
modules use. TZ 35.1 asks for `alembic upgrade head` to work, so this environment
exists alongside it and drives the *same* SQL files through the *same* marker
tables -- a database migrated by either path is recognised by the other, and
there is no second definition of the schema to drift.

The engine is async (asyncpg), so migrations run inside `connection.run_sync`.
"""
from __future__ import annotations

import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

alembic_config = context.config


def database_url() -> str:
    """DATABASE_URL from the environment, falling back to the app settings.

    Reading the env var directly means `alembic upgrade head` works with nothing
    but a database URL -- creating tables should not require a Telegram token or
    Yandex Cloud credentials to be present and valid.
    """
    import os

    url = os.getenv("DATABASE_URL")
    if url:
        return url
    from app.config import config as app_config  # noqa: PLC0415

    return app_config.database_url


if alembic_config.config_file_name is not None:
    fileConfig(alembic_config.config_file_name)

# The SQL files carry the schema; there is no declarative target to autogenerate
# against, and autogenerate against the ORM would fight the raw migrations.
target_metadata = None


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(database_url(), poolclass=NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
