"""Which SQL files make up the schema, and how "already applied" is recorded.

Deliberately free of any app.config import. Both the runtime runner
(app.database.run_migrations) and the Alembic baseline read from here, and
Alembic must be able to migrate a database without the full application
configuration being valid -- `alembic upgrade head` should not demand a Telegram
token or Yandex Cloud credentials to create tables.
"""
from __future__ import annotations

from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def migration_files() -> list[Path]:
    """The SQL migrations in apply order."""
    return sorted(MIGRATIONS_DIR.glob("*.sql")) if MIGRATIONS_DIR.exists() else []


def marker_table(migration_file: Path) -> str:
    """Per-file marker table recording that a migration has been applied.

    The migrations are plain DDL and not individually idempotent; the marker is
    what makes re-running safe -- including on a database migrated through the
    other path.
    """
    return f"_migration_{migration_file.stem}"


def split_sql(raw_sql: str) -> list[str]:
    """Split a SQL script into individual statements.

    Strips full-line ``--`` comments (our migrations only use line comments) and
    splits on ``;``. Robust enough for the project's DDL-only migrations.
    """
    lines = [ln for ln in raw_sql.splitlines() if not ln.strip().startswith("--")]
    return [stmt.strip() for stmt in "\n".join(lines).split(";") if stmt.strip()]
