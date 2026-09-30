"""Property statuses the router accepts must be the ones the table accepts."""
import os

import pytest

db_only = pytest.mark.skipif(os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL")


def test_router_statuses_match_the_check_constraint():
    from pathlib import Path

    from app.routers.properties import PROPERTY_STATUSES

    sql = (Path(__file__).resolve().parent.parent / "migrations" / "001_init.sql").read_text(encoding="utf-8")
    assert "CHECK (status IN ('active', 'sold', 'reserved', 'archive'))" in sql
    assert PROPERTY_STATUSES == {"active", "sold", "reserved", "archive"}


@db_only
@pytest.mark.asyncio
async def test_archiving_a_property_works_and_the_list_names_its_source():
    from app.database import async_session, engine, run_migrations
    from app.dependencies import CurrentManager
    from app.exceptions import AppException
    from app.models.agency import Agency
    from app.models.property import Property
    from app.routers.properties import UpdatePropertyRequest, _property_summary, update_property

    await run_migrations()
    try:
        async with async_session() as s:
            agency = Agency(name="Статусы", base_city="Сочи")
            s.add(agency)
            await s.flush()
            prop = Property(agency_id=agency.id, title="2-к. квартира", status="active",
                            source_system="avito", source_url="https://www.avito.ru/x")
            s.add(prop)
            await s.commit()
        ctx = CurrentManager("m", str(agency.id))
        async with async_session() as s:
            await update_property(prop.id, UpdatePropertyRequest(status="archived"), current=ctx, session=s)
        async with async_session() as s:
            prop = await s.get(Property, prop.id)
            assert prop.status == "archive"  # the old word is still understood
            assert _property_summary(prop)["source_system"] == "avito"
            with pytest.raises(AppException):
                await update_property(prop.id, UpdatePropertyRequest(status="draft"), current=ctx, session=s)
    finally:
        await engine.dispose()
