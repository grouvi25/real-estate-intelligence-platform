"""Async PostgreSQL engine, session factory, and SQL-file migration runner.

TZ section 5.2 (fixed): the illustrative TZ imported a non-existent ``TIMESTAMPTZ``
from ``sqlalchemy`` and called ``conn.commit()`` inside ``engine.begin()``. This is
a corrected, working implementation.
"""
from __future__ import annotations

from pathlib import Path

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import config

logger = structlog.get_logger()

# === Async engine ===
engine: AsyncEngine = create_async_engine(
    config.database_url,
    echo=config.node_env == "development",
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_recycle=3600,
)

async_session = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def get_session():
    """FastAPI dependency that yields a DB session and rolls back on error.

    Endpoints commit explicitly; this dependency only guarantees cleanup.
    """
    session = async_session()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def _split_sql(raw_sql: str) -> list[str]:
    """Split a SQL script into individual statements.

    Strips full-line ``--`` comments (our migrations only use line comments) and
    splits on ``;``. Robust enough for the project's DDL-only migrations.
    """
    lines = [ln for ln in raw_sql.splitlines() if not ln.strip().startswith("--")]
    cleaned = "\n".join(lines)
    return [stmt.strip() for stmt in cleaned.split(";") if stmt.strip()]


async def run_migrations() -> None:
    """Apply pending ``migrations/*.sql`` files idempotently.

    Each applied file is recorded via a marker table ``_migration_<stem>`` so it is
    never applied twice.
    """
    if not MIGRATIONS_DIR.exists():
        logger.warning("Migrations directory not found", path=str(MIGRATIONS_DIR))
        return

    for migration_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
        marker_table = f"_migration_{migration_file.stem}"
        async with engine.begin() as conn:
            already = await conn.execute(
                text(
                    "SELECT 1 FROM information_schema.tables WHERE table_name = :name"
                ),
                {"name": marker_table},
            )
            if already.scalar():
                logger.info("Migration already applied", file=migration_file.name)
                continue

            logger.info("Applying migration", file=migration_file.name)
            for stmt in _split_sql(migration_file.read_text(encoding="utf-8")):
                await conn.execute(text(stmt))

            await conn.execute(
                text(f'CREATE TABLE "{marker_table}" (applied_at TIMESTAMPTZ DEFAULT NOW())')
            )
            logger.info("Migration applied successfully", file=migration_file.name)


async def check_database_connection() -> bool:
    """Return True if a simple ``SELECT 1`` succeeds."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as e:  # noqa: BLE001
        logger.error("Database connection failed", error=str(e))
        return False
