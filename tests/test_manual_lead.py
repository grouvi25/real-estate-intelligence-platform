"""Entering a lead by hand. TZ 30 screen `/leads/new` (needs PostgreSQL).

Leads could only arrive from a Telegram signal or a lead-magnet subscribe, so a
manager who took a phone call had no way to put that person into the system --
even though leads.source_type has allowed 'manual' and 'incoming_call' since
migration 001, and TZ 30 lists the screen.
"""
import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL"
)


async def _agency(s, name="Manual Lead Agency"):
    from app.models.agency import Agency

    a = Agency(name=name, base_city="Геленджик")
    s.add(a)
    await s.flush()
    return a


def _current(agency):
    from app.dependencies import CurrentManager

    return CurrentManager(manager_id=str(uuid.uuid4()), agency_id=str(agency.id))


def _req(**over):
    from app.routers.leads import CreateLeadRequest

    base = {
        "name": "Иван Петров",
        "phone": "+79181234567",
        "consent_text": "Согласие получено по телефону",
        "source_type": "incoming_call",
        "urgency": "hot",
        "budget_max": 9_000_000,
    }
    base.update(over)
    return CreateLeadRequest(**base)


@pytest.fixture(autouse=True)
def _no_celery(monkeypatch):
    import worker.tasks.matching_tasks as mt

    monkeypatch.setattr(mt.run_matching_for_lead, "delay", lambda *a, **k: None)


@pytest.mark.asyncio
async def test_a_phone_call_becomes_a_lead():
    from app.database import async_session, run_migrations
    from app.models.lead import Lead
    from app.routers.leads import create_lead

    await run_migrations()
    async with async_session() as s:
        agency = await _agency(s)
        await s.commit()
        current = _current(agency)

    async with async_session() as s:
        res = await create_lead(_req(), current=current, session=s)

    assert res["is_duplicate"] is False
    assert res["matching_queued"] is True

    async with async_session() as s:
        lead = await s.get(Lead, uuid.UUID(res["lead_id"]))
    # PII is stored encrypted and comes back through the hybrid properties.
    assert lead.name == "Иван Петров"
    assert lead.phone == "+79181234567"
    assert lead.source_type == "incoming_call"
    assert lead.status == "new"
    assert lead.assigned_to is not None, "лид должен быть закреплён за создавшим менеджером"


@pytest.mark.asyncio
async def test_consent_is_recorded_not_just_accepted():
    """152-FZ: the text, the version and the moment all have to be stored."""
    from app.config import config
    from app.database import async_session, run_migrations
    from app.models.lead import Lead
    from app.routers.leads import create_lead

    await run_migrations()
    async with async_session() as s:
        agency = await _agency(s, "Consent Agency")
        await s.commit()
        current = _current(agency)

    async with async_session() as s:
        res = await create_lead(_req(consent_text="Согласие дано на встрече"),
                                current=current, session=s)

    async with async_session() as s:
        lead = await s.get(Lead, uuid.UUID(res["lead_id"]))
    assert lead.consent_given is True
    assert lead.consent_text == "Согласие дано на встрече"
    assert lead.consent_version == config.consent_version
    assert lead.consent_given_at is not None


@pytest.mark.asyncio
async def test_the_same_person_twice_does_not_create_a_second_lead():
    """TZ 35.7. check_and_mark_duplicate also merges the new source into the
    existing lead, so the second contact is not simply discarded."""
    from app.database import async_session, run_migrations
    from app.models.lead import Lead
    from app.routers.leads import create_lead
    from sqlalchemy import func, select

    await run_migrations()
    async with async_session() as s:
        agency = await _agency(s, "Dedup Agency")
        await s.commit()
        current = _current(agency)

    async with async_session() as s:
        first = await create_lead(_req(), current=current, session=s)
    async with async_session() as s:
        second = await create_lead(_req(source_type="referral"), current=current, session=s)

    assert second["is_duplicate"] is True
    assert second["lead_id"] == first["lead_id"]
    assert second["matching_queued"] is False

    async with async_session() as s:
        total = await s.scalar(
            select(func.count()).select_from(Lead).where(Lead.agency_id == uuid.UUID(current.agency_id))
        )
        lead = await s.get(Lead, uuid.UUID(first["lead_id"]))
    assert total == 1
    assert "referral" in (lead.buyer_profile or {}).get("all_sources", [])


@pytest.mark.asyncio
async def test_a_lead_with_no_way_to_reach_them_is_refused():
    from app.database import async_session, run_migrations
    from app.exceptions import ValidationError
    from app.routers.leads import create_lead

    await run_migrations()
    async with async_session() as s:
        agency = await _agency(s, "No Contact Agency")
        await s.commit()
        current = _current(agency)

    async with async_session() as s:
        with pytest.raises(ValidationError):
            await create_lead(_req(phone=None, telegram_username=None),
                              current=current, session=s)


@pytest.mark.asyncio
async def test_invalid_enumerations_are_refused():
    """The columns carry CHECK constraints; catching it here gives a readable
    message instead of a database error."""
    from app.database import async_session, run_migrations
    from app.exceptions import ValidationError
    from app.routers.leads import create_lead

    await run_migrations()
    async with async_session() as s:
        agency = await _agency(s, "Enum Agency")
        await s.commit()
        current = _current(agency)

    async with async_session() as s:
        for bad in ({"source_type": "signal"}, {"segment": "нечто"},
                    {"purchase_goal": "нечто"}, {"urgency": "очень"}):
            with pytest.raises(ValidationError):
                await create_lead(_req(**bad), current=current, session=s)


@pytest.mark.asyncio
async def test_a_backwards_budget_is_refused():
    from app.database import async_session, run_migrations
    from app.exceptions import ValidationError
    from app.routers.leads import create_lead

    await run_migrations()
    async with async_session() as s:
        agency = await _agency(s, "Budget Agency")
        await s.commit()
        current = _current(agency)

    async with async_session() as s:
        with pytest.raises(ValidationError):
            await create_lead(_req(budget_min=9_000_000, budget_max=5_000_000),
                              current=current, session=s)


@pytest.mark.asyncio
async def test_a_telegram_handle_alone_is_enough():
    from app.database import async_session, run_migrations
    from app.models.lead import Lead
    from app.routers.leads import create_lead

    await run_migrations()
    async with async_session() as s:
        agency = await _agency(s, "Handle Agency")
        await s.commit()
        current = _current(agency)

    async with async_session() as s:
        res = await create_lead(_req(phone=None, telegram_username="@buyer"),
                                current=current, session=s)

    async with async_session() as s:
        lead = await s.get(Lead, uuid.UUID(res["lead_id"]))
    # Stored without the "@" so it matches what the collector records.
    assert lead.telegram_username == "buyer"
