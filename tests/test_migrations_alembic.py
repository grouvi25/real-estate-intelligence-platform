"""Alembic path over the SQL migrations. TZ 35.1.

The schema lives in `migrations/*.sql` with an idempotent runner, which is what
production and 22 test modules use. TZ 35.1 additionally asks for
`alembic upgrade head` to work. Both paths must build the same schema and must
not fight each other, so the revision reuses the runner's own helpers.
"""
import os

import pytest


def test_baseline_revision_reuses_the_runner_helpers():
    """One definition of "which files, in what order, under which marker" -- so
    a new SQL file is picked up by both paths without touching either."""
    import importlib.util
    from pathlib import Path

    from app.database import marker_table, migration_files

    path = Path("alembic/versions/0001_sql_baseline.py")
    spec = importlib.util.spec_from_file_location("baseline", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.down_revision is None
    assert module.migration_files is migration_files
    assert module.marker_table is marker_table


def test_downgrade_refuses_to_drop_the_schema():
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "baseline", Path("alembic/versions/0001_sql_baseline.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with pytest.raises(NotImplementedError):
        module.downgrade()


def test_every_sql_file_has_a_distinct_marker():
    from app.database import marker_table, migration_files

    files = migration_files()
    assert files, "миграции не найдены"
    markers = [marker_table(f) for f in files]
    assert len(set(markers)) == len(markers)
    # PostgreSQL truncates identifiers at 63 characters; a collision there would
    # make one migration silently look applied.
    assert all(len(m) <= 63 for m in markers)


@pytest.mark.skipif(os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL")
@pytest.mark.asyncio
async def test_runner_is_idempotent_against_an_already_migrated_database():
    """What the Alembic baseline relies on: re-applying finds every marker and
    changes nothing."""
    from sqlalchemy import text

    from app.database import async_session, run_migrations

    await run_migrations()
    async with async_session() as s:
        before = (await s.execute(text(
            "select count(*) from information_schema.tables where table_schema='public'"
        ))).scalar()

    await run_migrations()
    async with async_session() as s:
        after = (await s.execute(text(
            "select count(*) from information_schema.tables where table_schema='public'"
        ))).scalar()

    assert before == after
