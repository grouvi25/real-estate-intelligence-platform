"""Go-live readiness checks. TZ 26 / 35.12 (needs PostgreSQL).

Every finding here was first discovered by poking at the live deployment and then
written down in a chat message. That is the wrong place for it: the next person
to look at the system has no way to know. The endpoint makes the same facts
answerable from the system itself.
"""
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL"
)


async def _agency(s, name="Readiness Agency"):
    from app.models.agency import Agency

    a = Agency(name=name, base_city="Геленджик")
    s.add(a)
    await s.flush()
    return a


@pytest.mark.asyncio
async def test_empty_catalogue_blocks_go_live():
    """The system found a real buyer with a 5M budget and had two invented
    objects to offer. Nothing on /health/deep says so."""
    from app.database import async_session, run_migrations
    from app.services.readiness import readiness_report

    await run_migrations()
    async with async_session() as s:
        agency = await _agency(s, "Empty Catalogue Agency")
        await s.commit()
        report = await readiness_report(s, str(agency.id))

    assert report["ready"] is False
    assert report["findings"]["catalogue"]["severity"] == "blocker"
    assert "Загрузите каталог" in report["findings"]["catalogue"]["action"]


@pytest.mark.asyncio
async def test_a_stocked_catalogue_clears_that_finding():
    from app.database import async_session, run_migrations
    from app.models.property import Property
    from app.services.readiness import readiness_report

    await run_migrations()
    async with async_session() as s:
        agency = await _agency(s)
        s.add(Property(agency_id=agency.id, title="Квартира", price=8_000_000, status="active"))
        await s.commit()
        report = await readiness_report(s, str(agency.id))

    assert "catalogue" not in report["findings"]
    # A single object is still suspicious -- see the seed-size test below.
    assert report["findings"]["catalogue_size"]["severity"] == "warning"


@pytest.mark.asyncio
async def test_archived_objects_do_not_count_as_a_catalogue():
    """An agency whose objects are all sold has nothing to offer either."""
    from app.database import async_session, run_migrations
    from app.models.property import Property
    from app.services.readiness import readiness_report

    await run_migrations()
    async with async_session() as s:
        agency = await _agency(s, "Sold Out Agency")
        s.add(Property(agency_id=agency.id, title="Продана", price=1, status="sold"))
        await s.commit()
        report = await readiness_report(s, str(agency.id))

    assert report["findings"]["catalogue"]["severity"] == "blocker"


@pytest.mark.asyncio
async def test_missing_sources_and_collector_are_blockers(monkeypatch):
    from app.database import async_session, run_migrations
    from app.services import readiness as r
    from app.services.readiness import readiness_report

    monkeypatch.setattr(r.config, "telethon_api_id", None)
    monkeypatch.setattr(r.config, "telethon_api_hash", None)

    await run_migrations()
    async with async_session() as s:
        agency = await _agency(s, "No Sources Agency")
        await s.commit()
        report = await readiness_report(s, str(agency.id))

    assert report["findings"]["sources"]["severity"] == "blocker"
    assert report["findings"]["collector"]["severity"] == "blocker"


@pytest.mark.asyncio
async def test_placeholder_credentials_are_reported(monkeypatch):
    """Production ran for weeks with YC_FOLDER_ID=dev and nothing said a word."""
    from app.database import async_session, run_migrations
    from app.services import readiness as r
    from app.services.readiness import readiness_report

    monkeypatch.setattr(r.config, "yc_folder_id", "dev")
    monkeypatch.setattr(r.config, "max_bot_token", None)
    monkeypatch.setattr(r.config, "node_env", "development")

    await run_migrations()
    async with async_session() as s:
        agency = await _agency(s, "Placeholder Agency")
        await s.commit()
        report = await readiness_report(s, str(agency.id))

    assert report["findings"]["yandex_cloud"]["severity"] == "warning"
    assert report["findings"]["max"]["severity"] == "warning"
    assert report["findings"]["node_env"]["severity"] == "warning"


@pytest.mark.asyncio
async def test_shared_collector_account_is_flagged(monkeypatch):
    """One ban on that number takes out collection and notifications together."""
    from app.database import async_session, run_migrations
    from app.services import readiness as r
    from app.services.readiness import readiness_report

    monkeypatch.setattr(r.config, "telethon_phone", "+70000000000")
    monkeypatch.setattr(r.config, "admin_telegram_id", 7503416516)

    await run_migrations()
    async with async_session() as s:
        agency = await _agency(s, "Shared Account Agency")
        await s.commit()
        report = await readiness_report(s, str(agency.id))

    assert report["findings"]["collector_account"]["severity"] == "warning"
    assert "отдельный номер" in report["findings"]["collector_account"]["action"]


@pytest.mark.asyncio
async def test_real_configuration_reports_ready(monkeypatch):
    """Guard against a check that can never be satisfied."""
    from app.database import async_session, run_migrations
    from app.models.property import Property
    from app.models.source import Source
    from app.services import readiness as r
    from app.services.readiness import readiness_report

    monkeypatch.setattr(r.config, "telethon_api_id", 12345)
    monkeypatch.setattr(r.config, "telethon_api_hash", "abcdef0123456789")
    monkeypatch.setattr(r.config, "telethon_phone", None)
    monkeypatch.setattr(r.config, "telegram_bot_token", "8985346019:AAF-real-looking")
    monkeypatch.setattr(r.config, "max_bot_token", "max-real-token")
    monkeypatch.setattr(r.config, "yc_folder_id", "b1gxxxxxxxxxxxxx")
    monkeypatch.setattr(r.config, "node_env", "production")
    monkeypatch.setattr(r.config, "database_url",
                        "postgresql+asyncpg://re_app:s3cret@db:5432/realestate")

    await run_migrations()
    async with async_session() as s:
        agency = await _agency(s, "Ready Agency")
        for i in range(6):
            s.add(Property(agency_id=agency.id, title=f"Квартира {i}", price=8_000_000, status="active"))
        s.add(Source(agency_id=agency.id, source_type="telegram_chat",
                     source_url="https://t.me/x", status="active"))
        await s.commit()
        report = await readiness_report(s, str(agency.id))

    assert report["ready"] is True, report["findings"]
    assert report["blockers"] == 0


@pytest.mark.asyncio
async def test_a_seed_sized_catalogue_is_flagged_but_not_blocking():
    """Production reported itself ready on two demo objects. The count is the
    only signal available -- nothing marks a row as seeded -- so it is raised as
    a suspicion rather than a blocker."""
    from app.database import async_session, run_migrations
    from app.models.property import Property
    from app.services.readiness import SEED_CATALOGUE_MAX, readiness_report

    await run_migrations()
    async with async_session() as s:
        agency = await _agency(s, "Seed Sized Agency")
        for i in range(2):
            s.add(Property(agency_id=agency.id, title=f"Демо {i}", price=1_000_000, status="active"))
        await s.commit()
        report = await readiness_report(s, str(agency.id))

    assert report["findings"]["catalogue_size"]["severity"] == "warning"
    assert "catalogue" not in report["findings"]

    async with async_session() as s:
        agency = await _agency(s, "Stocked Agency")
        for i in range(SEED_CATALOGUE_MAX + 1):
            s.add(Property(agency_id=agency.id, title=f"Объект {i}", price=8_000_000, status="active"))
        await s.commit()
        report = await readiness_report(s, str(agency.id))

    assert "catalogue_size" not in report["findings"]
