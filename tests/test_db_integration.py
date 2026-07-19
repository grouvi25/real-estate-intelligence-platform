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


@pytest.mark.asyncio
async def test_reset_daily_ai_cost_clears_global_counter():
    from app.config import config
    from app.services.ai_cost_tracker import RedisCostTracker
    from worker.tasks.maintenance_tasks import _reset_daily_ai_cost

    tracker = RedisCostTracker(config.redis_url)
    await tracker.add_cost(12.5)
    assert await tracker.get_daily_cost() > 0

    await _reset_daily_ai_cost()  # resets global + all agencies

    assert await tracker.get_daily_cost() == 0.0
    await tracker.redis.aclose()


@pytest.mark.asyncio
async def test_full_chain_insert_and_pii_at_rest():
    """Insert across agency->geo->source->signal->lead and verify PII encryption."""
    from app.database import async_session, run_migrations
    from app.models.agency import Agency
    from app.models.geo_location import GeoLocation
    from app.models.lead import Lead
    from app.models.signal import Signal
    from app.models.source import Source

    await run_migrations()

    async with async_session() as s:
        agency = Agency(name="Chain Agency", base_city="Геленджик")
        s.add(agency)
        await s.flush()

        geo = GeoLocation(agency_id=agency.id, city_name="Геленджик", region="Краснодарский край", geo_type="base")
        s.add(geo)
        await s.flush()

        source = Source(agency_id=agency.id, geo_location_id=geo.id, source_type="telegram_chat", source_url="https://t.me/x", source_name="Чат")
        s.add(source)
        await s.flush()

        signal = Signal(agency_id=agency.id, source_id=source.id, geo_location_id=geo.id, raw_text="ищу квартиру у моря до 8 млн")
        s.add(signal)
        await s.flush()

        lead = Lead(agency_id=agency.id, geo_location_id=geo.id, signal_id=signal.id, source_type="signal")
        lead.name = "Иван Петров"
        lead.phone = "+79001234567"
        s.add(lead)
        await s.commit()
        lead_id = lead.id
        signal_id = signal.id

    async with async_session() as s:
        got_lead = await s.get(Lead, lead_id)
        assert got_lead.phone == "+79001234567"  # decrypts
        assert got_lead._phone_encrypted is not None
        assert got_lead._phone_encrypted != b"+79001234567"  # stored encrypted

        got_signal = await s.get(Signal, signal_id)
        # eager-joined relationship resolves the geo city
        assert got_signal.geo_location is not None
        assert got_signal.geo_location.city_name == "Геленджик"
        assert got_signal.source.source_name == "Чат"
