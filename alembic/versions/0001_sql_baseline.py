"""Apply the SQL migration files. TZ 35.1.

Revision ID: 0001_sql_baseline
Revises:
Create Date: 2026-07-31

The schema lives in `migrations/*.sql`. This revision applies exactly those
files, through exactly the marker tables app.database.run_migrations uses, so:

  * a fresh database can be built with `alembic upgrade head`;
  * a database already migrated by the runner (production, and every test that
    calls run_migrations) is left untouched -- each file's marker is present, so
    nothing re-runs;
  * new SQL files are picked up by both paths without a new revision.

The files are plain DDL and not individually idempotent; the markers are what
makes re-running safe.
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text

from app.sql_migrations import marker_table, migration_files, split_sql

revision = "0001_sql_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    for migration_file in migration_files():
        marker = marker_table(migration_file)
        already = conn.execute(
            text("SELECT 1 FROM information_schema.tables WHERE table_name = :name"),
            {"name": marker},
        ).scalar()
        if already:
            continue

        for stmt in split_sql(migration_file.read_text(encoding="utf-8")):
            conn.execute(text(stmt))
        conn.execute(
            text(f'CREATE TABLE "{marker}" (applied_at TIMESTAMPTZ DEFAULT NOW())')
        )


def downgrade() -> None:
    # Dropping the schema would destroy the agency's data, including personal
    # data the system is accountable for under 152-FZ. Restore from a backup
    # instead.
    raise NotImplementedError(
        "Откат схемы не поддерживается: восстанавливайте из резервной копии"
    )
