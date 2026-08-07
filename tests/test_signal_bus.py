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
        # 'replied' is the addendum's word for a delivered answer (§5.2).
        assert sig.reply_status == "replied"
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


# --- the two ways a signal leaves the queue unanswered (addendum §5.2) -------

@pytest.mark.skipif(os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL")
@pytest.mark.asyncio
async def test_an_irrelevant_signal_can_be_dropped(monkeypatch):
    """Nothing removed a signal that was never worth answering, so the queue
    only ever grew and real signals sank under the noise."""
    import uuid as _uuid

    from app.database import async_session, run_migrations
    from app.dependencies import CurrentManager
    from app.models.agency import Agency
    from app.models.manager import Manager
    from app.models.signal import Signal
    from app.routers.signals import TriageRequest, dismiss_signal, signal_reply_queue

    await run_migrations()
    async with async_session() as s:
        agency = Agency(name=f"Triage {_uuid.uuid4().hex[:6]}", base_city="Геленджик")
        s.add(agency)
        await s.flush()
        manager = Manager(agency_id=agency.id, name="М", role="manager",
                          telegram_id=770000 + int(_uuid.uuid4().int % 90000), is_active=True)
        s.add(manager)
        signal = Signal(agency_id=agency.id, raw_text="Продам гараж", status="new",
                        origin_system="reip_scouting", intent_score=12)
        s.add(signal)
        await s.commit()
        ctx = CurrentManager(manager_id=str(manager.id), agency_id=str(agency.id))
        signal_id = signal.id

    async with async_session() as s:
        # A freshly collected signal has no reply state and belongs in the queue.
        assert any(str(signal_id) == x["id"] for x in
                   (await signal_reply_queue(current=ctx, session=s))["signals"])

    async with async_session() as s:
        signal = await s.get(Signal, signal_id)
        await dismiss_signal(signal_id, TriageRequest(reason="Не покупатель"),
                             current=ctx, session=s)

    async with async_session() as s:
        signal = await s.get(Signal, signal_id)
        queue = await signal_reply_queue(current=ctx, session=s)

    assert signal.reply_status == "dismissed"
    assert signal.triage_reason == "Не покупатель"
    assert signal.triaged_at is not None
    assert all(x["id"] != str(signal_id) for x in queue["signals"]), "убранное не должно возвращаться"


@pytest.mark.skipif(os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL")
@pytest.mark.asyncio
async def test_escalation_reaches_the_owner(monkeypatch):
    """An escalation nobody hears about is a signal that stopped moving."""
    import uuid as _uuid

    import app.services.alerts as alerts_mod
    import app.services.bot_abstraction as ba
    from app.database import async_session, run_migrations
    from app.dependencies import CurrentManager
    from app.models.agency import Agency
    from app.models.manager import Manager
    from app.models.signal import Signal
    from app.routers.signals import TriageRequest, escalate_signal

    sent = []

    class _Bot:
        async def notify_manager(self, manager_id, text):
            sent.append((manager_id, text))
            return True

    monkeypatch.setattr(ba, "bot_layer", _Bot())
    monkeypatch.setattr(alerts_mod, "bot_layer", _Bot(), raising=False)

    await run_migrations()
    async with async_session() as s:
        agency = Agency(name=f"Esc {_uuid.uuid4().hex[:6]}", base_city="Геленджик")
        s.add(agency)
        await s.flush()
        owner = Manager(agency_id=agency.id, name="Владелец", role="owner",
                        telegram_id=780000 + int(_uuid.uuid4().int % 90000), is_active=True)
        staff = Manager(agency_id=agency.id, name="М", role="manager",
                        telegram_id=790000 + int(_uuid.uuid4().int % 90000), is_active=True)
        s.add_all([owner, staff])
        signal = Signal(agency_id=agency.id, raw_text="Сложный запрос", status="new",
                        origin_system="reip_scouting", intent_score=77)
        s.add(signal)
        await s.commit()
        ctx = CurrentManager(manager_id=str(staff.id), agency_id=str(agency.id))
        signal_id, owner_id = signal.id, owner.id

    async with async_session() as s:
        signal = await s.get(Signal, signal_id)
        await escalate_signal(signal_id, TriageRequest(reason="Нужен старший"),
                              current=ctx, session=s)

    async with async_session() as s:
        signal = await s.get(Signal, signal_id)

    assert signal.reply_status == "escalated"
    assert signal.triaged_by_manager_id is not None
    assert sent and sent[0][0] == owner_id
    assert "Сложный запрос" in sent[0][1]
