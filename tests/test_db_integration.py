"""Database integration tests: apply migrations, then CRUD with real PostgreSQL.

Gated behind RUN_DB_TESTS=1 so unit runs (and machines without Postgres) skip it.
In CI a postgres:15 service is provided and RUN_DB_TESTS=1 is set.
"""
import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_TESTS") != "1",
    reason="DB integration tests disabled (set RUN_DB_TESTS=1 with a live PostgreSQL)",
)


@pytest.fixture(autouse=True)
async def _dispose_engine_after_test():
    """Dispose the shared async engine after each test.

    The module-level engine binds its asyncpg pool to the event loop that first
    used it. pytest-asyncio gives each test a fresh loop, so without disposing
    between tests a pooled connection would be reused across loops
    ("attached to a different loop"). Disposing in the test's own loop fixes it.
    """
    yield
    from app.database import engine

    await engine.dispose()


@pytest.mark.asyncio
async def test_migrations_apply_and_are_idempotent():
    from sqlalchemy import text

    from app.database import engine, run_migrations

    await run_migrations()
    # Second run must be a no-op (marker table already present).
    await run_migrations()

    async with engine.connect() as conn:
        # Core tables from migration 001 exist.
        for table in ("agencies", "managers", "signals", "leads", "properties"):
            res = await conn.execute(
                text("SELECT to_regclass(:t)"), {"t": f"public.{table}"}
            )
            assert res.scalar() is not None, f"table {table} missing"


@pytest.mark.asyncio
async def test_agency_manager_crud_with_encryption():
    from sqlalchemy import select

    from app.database import async_session, run_migrations
    from app.models.agency import Agency
    from app.models.manager import Manager

    await run_migrations()

    tg_id = 100000 + uuid.uuid4().int % 100000
    async with async_session() as s:
        agency = Agency(name="Тест-Агентство", base_city="Геленджик")
        s.add(agency)
        await s.flush()
        mgr = Manager(agency_id=agency.id, name="Иван", telegram_id=tg_id)
        mgr.phone = "+79001234567"
        s.add(mgr)
        await s.commit()
        manager_id = mgr.id

    # Verify raw storage is encrypted (ciphertext != plaintext bytes).
    async with async_session() as s:
        got = await s.get(Manager, manager_id)
        assert got is not None
        assert got.name == "Иван"
        assert got._phone_encrypted is not None
        assert got._phone_encrypted != b"+79001234567"
        assert got.phone == "+79001234567"  # decrypts back

        agencies = (await s.execute(select(Agency))).scalars().all()
        assert any(a.base_city == "Геленджик" for a in agencies)
