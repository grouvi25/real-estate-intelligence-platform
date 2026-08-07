"""152-ФЗ: the subject's rights over their own data (TZ manifest, section 3).

Consent was recorded from the first commit. The other half of the law had no
implementation at all: no way to show a person what is held about them (§14) and
no way to erase it (§21) other than hand-written SQL, which is not a process
that can be demonstrated to anyone.
"""
import os
import uuid
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL"
)


async def _lead_with_signal(s):
    from app.models.agency import Agency
    from app.models.lead import Lead
    from app.models.signal import Signal

    agency = Agency(name=f"PD {uuid.uuid4().hex[:6]}", base_city="Геленджик")
    s.add(agency)
    await s.flush()

    signal = Signal(agency_id=agency.id, raw_text="Меня зовут Анна, тел +7 918 000-00-00",
                    status="qualified", origin_system="reip_scouting")
    s.add(signal)
    await s.flush()

    lead = Lead(agency_id=agency.id, source_type="signal", status="qualified",
                source_signal_id=signal.id, consent_given=True,
                consent_given_at=datetime.now(timezone.utc),
                consent_text="Согласие получено в чате", buyer_profile={"note": "Анна"})
    lead.name = "Анна Соколова"
    lead.phone = "+79180000000"
    lead.email = "anna@example.com"
    lead.telegram_username = "anna"
    s.add(lead)
    await s.commit()
    return agency, lead, signal


@pytest.mark.asyncio
async def test_the_subject_can_be_shown_what_is_held_about_them():
    from app.database import async_session, run_migrations
    from app.services.consent_manager import export_lead_data

    await run_migrations()
    async with async_session() as s:
        _, lead, _ = await _lead_with_signal(s)
        data = await export_lead_data(s, lead)

    # Decrypted on purpose: it is their own data, a ciphertext answers nothing.
    assert data["lead"]["name"] == "Анна Соколова"
    assert data["lead"]["phone"] == "+79180000000"
    assert data["consent"]["text"] == "Согласие получено в чате"
    assert data["source_signals"] and "Анна" in data["source_signals"][0]["text"]


@pytest.mark.asyncio
async def test_erasure_destroys_the_identifiers_and_keeps_the_accounting():
    from app.database import async_session, run_migrations
    from app.models.lead import Lead
    from app.models.signal import Signal
    from app.services.consent_manager import ERASED_MARK, erase_lead_data

    await run_migrations()
    async with async_session() as s:
        _, lead, signal = await _lead_with_signal(s)
        lead_id, signal_id = lead.id, signal.id
        result = await erase_lead_data(s, lead, reason="Отзыв согласия")

    assert result["erased"] is True
    async with async_session() as s:
        lead = await s.get(Lead, lead_id)
        signal = await s.get(Signal, signal_id)

    assert lead.name is None and lead.phone is None and lead.email is None
    assert lead.telegram_username is None
    # The blind index is derived from the number, so it goes too.
    assert lead.phone_hash is None
    assert lead.buyer_profile == {}
    assert lead.consent_given is False
    assert lead.pd_erased_at is not None
    # The person's own words often carry the name inside the text.
    assert signal.raw_text == ERASED_MARK
    # ...and the row itself survives: it is the agency's accounting.
    assert lead.status == "archived"


@pytest.mark.asyncio
async def test_erasure_leaves_a_trace_that_it_happened():
    """"We erased it" has to be provable afterwards."""
    from sqlalchemy import select

    from app.database import async_session, run_migrations
    from app.models.activity_log import ActivityLog
    from app.services.consent_manager import erase_lead_data

    await run_migrations()
    async with async_session() as s:
        _, lead, _ = await _lead_with_signal(s)
        lead_id = lead.id
        await erase_lead_data(s, lead, reason="Отзыв согласия")

    async with async_session() as s:
        entries = (await s.execute(
            select(ActivityLog).where(ActivityLog.lead_id == lead_id)
        )).scalars().all()

    actions = [e.action_type for e in entries]
    assert "pd_erased" in actions
    entry = next(e for e in entries if e.action_type == "pd_erased")
    assert entry.meta.get("reason") == "Отзыв согласия"


@pytest.mark.asyncio
async def test_a_subject_is_found_by_the_number_they_call_from():
    """Requests arrive as "удалите мои данные, мой номер такой-то"."""
    from app.database import async_session, run_migrations
    from app.services.consent_manager import find_leads_by_phone

    await run_migrations()
    async with async_session() as s:
        agency, lead, _ = await _lead_with_signal(s)
        found = await find_leads_by_phone(s, agency.id, "+7 918 000-00-00")

    assert [x.id for x in found] == [lead.id]
