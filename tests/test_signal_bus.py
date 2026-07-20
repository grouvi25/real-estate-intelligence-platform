"""Signal Bus service tests (need PostgreSQL). Ingestion + reply workflow."""
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL"
)


async def _agency(s):
    from app.models.agency import Agency

    a = Agency(name="SB Agency", base_city="Сочи")
    s.add(a)
    await s.flush()
    return a


@pytest.mark.asyncio
async def test_ingest_content_upserts():
    from app.database import async_session, run_migrations
    from app.services.signal_bus import ingest_content

    await run_migrations()
    async with async_session() as s:
        agency = await _agency(s)
        raw = {"message_id": 9, "chat": {"id": 500}, "from": {"id": 3, "username": "bob"},
               "text": "Куплю студию", "date": 1700000000}
        cu1 = await ingest_content(s, agency.id, "telegram", raw)
        assert cu1 is not None
        assert cu1.external_id == "500:9"
        await s.commit()
        cu1_id = cu1.id

        # Re-ingest same external id -> same row (upsert).
        raw["text"] = "Куплю студию срочно"
        cu2 = await ingest_content(s, agency.id, "telegram", raw)
        await s.commit()
        assert cu2.id == cu1_id
        assert cu2.raw_content == "Куплю студию срочно"


@pytest.mark.asyncio
async def test_ingest_unknown_channel_returns_none():
    from app.database import async_session, run_migrations
    from app.services.signal_bus import ingest_content

    await run_migrations()
    async with async_session() as s:
        agency = await _agency(s)
        assert await ingest_content(s, agency.id, "myspace", {"id": 1}) is None


@pytest.mark.asyncio
async def test_send_reply_telegram(monkeypatch):
    from app.database import async_session, run_migrations
    from app.models.content_unit import ContentUnit
    from app.models.signal import Signal
    from app.services.signal_bus import send_signal_reply

    # Avoid network: stub the bot layer.
    import app.services.bot_abstraction as ba

    async def _fake_send(user_id, platform, message):
        return True

    monkeypatch.setattr(ba.bot_layer, "send_message", _fake_send)

    await run_migrations()
    async with async_session() as s:
        agency = await _agency(s)
        cu = ContentUnit(agency_id=agency.id, channel="telegram", external_id="500:9",
                         content_type="message", raw_content="Куплю")
        s.add(cu)
        await s.flush()
        sig = Signal(agency_id=agency.id, raw_text="Куплю", origin_system="telegram",
                     content_unit_id=cu.id, reply_channel="telegram",
                     reply_draft="Здравствуйте! Подберу варианты.", reply_status="draft")
        s.add(sig)
        await s.commit()
        sig_id = sig.id

    async with async_session() as s:
        sig = await s.get(Signal, sig_id)
        result = await send_signal_reply(s, sig, manager_id=None)
        assert result["sent"] is True

    async with async_session() as s:
        sig = await s.get(Signal, sig_id)
        assert sig.reply_status == "sent"
        assert sig.replied_at is not None


@pytest.mark.asyncio
async def test_send_reply_classified_skipped():
    from app.database import async_session, run_migrations
    from app.models.content_unit import ContentUnit
    from app.models.signal import Signal
    from app.services.signal_bus import send_signal_reply

    await run_migrations()
    async with async_session() as s:
        agency = await _agency(s)
        cu = ContentUnit(agency_id=agency.id, channel="avito", external_id="777",
                         content_type="listing", raw_content="Продам")
        s.add(cu)
        await s.flush()
        sig = Signal(agency_id=agency.id, raw_text="Продам", origin_system="avito",
                     content_unit_id=cu.id, reply_channel="avito",
                     reply_draft="Ответ", reply_status="draft")
        s.add(sig)
        await s.commit()
        sig_id = sig.id

    async with async_session() as s:
        sig = await s.get(Signal, sig_id)
        result = await send_signal_reply(s, sig)
        assert result["sent"] is False
    async with async_session() as s:
        sig = await s.get(Signal, sig_id)
        assert sig.reply_status == "skipped"
