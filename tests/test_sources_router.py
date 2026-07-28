"""Monitoring source management endpoint tests (need PostgreSQL). TZ 30, 15.

Discovery writes sources and the collector reads them; this router is the only
way to see what the engine picked and to stop a bad source without an UPDATE
against the database.
"""
import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL"
)


async def _agency_with_geo(s):
    from app.models.agency import Agency
    from app.models.geo_location import GeoLocation

    agency = Agency(name="Sources Agency", base_city="Геленджик")
    s.add(agency)
    await s.flush()
    geo = GeoLocation(agency_id=agency.id, city_name="Геленджик", geo_type="sales")
    s.add(geo)
    await s.flush()
    return agency, geo


def _current(agency):
    from app.dependencies import CurrentManager

    return CurrentManager(manager_id=str(uuid.uuid4()), agency_id=str(agency.id))


@pytest.mark.asyncio
async def test_add_source_by_username_and_list_it():
    from app.database import async_session, run_migrations
    from app.routers.sources import CreateSourceRequest, create_source, list_sources

    await run_migrations()
    async with async_session() as s:
        agency, geo = await _agency_with_geo(s)
        await s.commit()
        current = _current(agency)

    async with async_session() as s:
        created = await create_source(
            CreateSourceRequest(source_url="@gelendzhik_chat", geo_location_id=geo.id),
            current=current, session=s)

    # "@name" is normalised to a t.me URL, and the username is stored in
    # external_id because that is what the collector resolves sources by.
    assert created["source_url"] == "https://t.me/gelendzhik_chat"
    assert created["external_id"] == "gelendzhik_chat"
    assert created["status"] == "sandbox"
    assert created["auto_found"] is False

    async with async_session() as s:
        listed = await list_sources(current=current, session=s)
    assert listed["count"] == 1
    assert listed["sources"][0]["city_name"] == "Геленджик"


@pytest.mark.asyncio
async def test_duplicate_source_is_rejected():
    from app.database import async_session, run_migrations
    from app.exceptions import ValidationError
    from app.routers.sources import CreateSourceRequest, create_source

    await run_migrations()
    async with async_session() as s:
        agency, _ = await _agency_with_geo(s)
        await s.commit()
        current = _current(agency)

    async with async_session() as s:
        await create_source(CreateSourceRequest(source_url="https://t.me/dup_chat"),
                            current=current, session=s)
        with pytest.raises(ValidationError):
            await create_source(CreateSourceRequest(source_url="https://t.me/dup_chat"),
                                current=current, session=s)


@pytest.mark.asyncio
async def test_pause_a_source_so_the_collector_skips_it():
    """The live rental chat had to be paused with raw SQL; this is the fix."""
    from app.database import async_session, run_migrations
    from app.routers.sources import (
        CreateSourceRequest,
        UpdateSourceRequest,
        create_source,
        list_sources,
        update_source,
    )

    await run_migrations()
    async with async_session() as s:
        agency, _ = await _agency_with_geo(s)
        await s.commit()
        current = _current(agency)

    async with async_session() as s:
        created = await create_source(
            CreateSourceRequest(source_url="https://t.me/rental_chat", status="active"),
            current=current, session=s)
        updated = await update_source(uuid.UUID(created["id"]),
                                      UpdateSourceRequest(status="paused"),
                                      current=current, session=s)
        assert updated["status"] == "paused"

    async with async_session() as s:
        # The collector only reads active/sandbox.
        active = await list_sources(status="active", current=current, session=s)
        assert active["count"] == 0
        paused = await list_sources(status="paused", current=current, session=s)
        assert paused["count"] == 1


@pytest.mark.asyncio
async def test_delete_is_blocked_while_signals_reference_the_source():
    from app.database import async_session, run_migrations
    from app.exceptions import AppException
    from app.models.signal import Signal
    from app.routers.sources import CreateSourceRequest, create_source, delete_source

    await run_migrations()
    async with async_session() as s:
        agency, _ = await _agency_with_geo(s)
        await s.commit()
        current = _current(agency)

    async with async_session() as s:
        created = await create_source(CreateSourceRequest(source_url="https://t.me/busy_chat"),
                                      current=current, session=s)
        s.add(Signal(agency_id=agency.id, source_id=uuid.UUID(created["id"]),
                     raw_text="Куплю квартиру в Геленджике"))
        await s.commit()

    async with async_session() as s:
        with pytest.raises(AppException) as e:
            await delete_source(uuid.UUID(created["id"]), current=current, session=s)
        # Deleting would break v_signal_to_outcome attribution and Source ROI.
        assert e.value.status_code == 409


@pytest.mark.asyncio
async def test_delete_removes_a_source_with_no_signals():
    from app.database import async_session, run_migrations
    from app.routers.sources import CreateSourceRequest, create_source, delete_source, list_sources

    await run_migrations()
    async with async_session() as s:
        agency, _ = await _agency_with_geo(s)
        await s.commit()
        current = _current(agency)

    async with async_session() as s:
        created = await create_source(CreateSourceRequest(source_url="https://t.me/empty_chat"),
                                      current=current, session=s)
        res = await delete_source(uuid.UUID(created["id"]), current=current, session=s)
        assert res["deleted"] is True

    async with async_session() as s:
        assert (await list_sources(current=current, session=s))["count"] == 0


@pytest.mark.asyncio
async def test_sources_are_scoped_to_the_token_agency():
    from app.database import async_session, run_migrations
    from app.exceptions import NotFoundError
    from app.models.agency import Agency
    from app.routers.sources import (
        CreateSourceRequest,
        UpdateSourceRequest,
        create_source,
        list_sources,
        update_source,
    )

    await run_migrations()
    async with async_session() as s:
        agency, _ = await _agency_with_geo(s)
        other = Agency(name="Other Sources Agency", base_city="Сочи")
        s.add(other)
        await s.commit()
        current, stranger = _current(agency), _current(other)

    async with async_session() as s:
        created = await create_source(CreateSourceRequest(source_url="https://t.me/scoped_chat"),
                                      current=current, session=s)

    async with async_session() as s:
        assert (await list_sources(current=stranger, session=s))["count"] == 0
        with pytest.raises(NotFoundError):
            await update_source(uuid.UUID(created["id"]), UpdateSourceRequest(status="active"),
                                current=stranger, session=s)


@pytest.mark.asyncio
async def test_rejects_invalid_type_status_and_score():
    from app.database import async_session, run_migrations
    from app.exceptions import ValidationError
    from app.routers.sources import (
        CreateSourceRequest,
        UpdateSourceRequest,
        create_source,
        update_source,
    )

    await run_migrations()
    async with async_session() as s:
        agency, _ = await _agency_with_geo(s)
        await s.commit()
        current = _current(agency)

    async with async_session() as s:
        with pytest.raises(ValidationError):
            await create_source(CreateSourceRequest(source_url="https://t.me/x", source_type="carrier_pigeon"),
                                current=current, session=s)
        with pytest.raises(ValidationError):
            await create_source(CreateSourceRequest(source_url="https://t.me/x", status="nonsense"),
                                current=current, session=s)
        with pytest.raises(ValidationError):
            await create_source(CreateSourceRequest(source_url="   "), current=current, session=s)

        created = await create_source(CreateSourceRequest(source_url="https://t.me/score_chat"),
                                      current=current, session=s)
        with pytest.raises(ValidationError):
            await update_source(uuid.UUID(created["id"]), UpdateSourceRequest(score=500),
                                current=current, session=s)
