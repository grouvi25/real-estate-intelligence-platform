"""Partner referrals tests (needs PostgreSQL): create + expiry. Bot is mocked."""
import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL"
)


async def _seed(session):
    from app.models.agency import Agency
    from app.models.lead import Lead
    from app.models.manager import Manager
    from app.models.partner_agency import PartnerAgency

    agency = Agency(name="Ref Agency", base_city="Геленджик")
    session.add(agency)
    await session.flush()
    manager = Manager(agency_id=agency.id, name="Менеджер", role="manager")
    session.add(manager)
    lead = Lead(agency_id=agency.id, source_type="signal", segment="family",
                budget_min=5_000_000, budget_max=8_000_000, status="new")
    session.add(lead)
    partner = PartnerAgency(agency_id=agency.id, partner_name="Сочи Партнёр", partner_city="Сочи",
                            contact_telegram="123456", commission_percent=30.0, is_active=True)
    session.add(partner)
    await session.commit()
    return agency, manager, lead, partner


@pytest.mark.asyncio
async def test_create_referral(monkeypatch):
    import app.services.bot_abstraction as ba
    from app.database import async_session, run_migrations
    from app.dependencies import CurrentManager
    from app.models.partner_referral import PartnerReferral
    from app.models.task import Task
    from app.routers.referrals import CreateReferralRequest, create_referral

    sent = []

    async def fake_send(user_id, platform, message):
        sent.append(user_id)
        return True

    monkeypatch.setattr(ba.bot_layer, "send_message", fake_send)

    await run_migrations()
    async with async_session() as s:
        agency, manager, lead, partner = await _seed(s)
        current = CurrentManager(manager_id=str(manager.id), agency_id=str(agency.id))
        lead_id, partner_id = lead.id, partner.id

    async with async_session() as s:
        resp = await create_referral(
            CreateReferralRequest(lead_id=lead_id, partner_agency_id=partner_id, terms="50/50"),
            current=current, session=s,
        )
    assert resp["status"] == "sent_to_partner"
    assert sent == [123456]  # partner notified

    async with async_session() as s:
        from app.models.lead import Lead

        lead = await s.get(Lead, lead_id)
        assert lead.status == "referred" and lead.referred_to == partner_id
        refs = (await s.execute(select(PartnerReferral).where(PartnerReferral.lead_id == lead_id))).scalars().all()
        assert len(refs) == 1 and refs[0].status == "pending"
        tasks = (await s.execute(select(Task).where(Task.lead_id == lead_id, Task.task_type == "referral_confirmation"))).scalars().all()
        assert len(tasks) == 1


@pytest.mark.asyncio
async def test_check_referral_expiry(monkeypatch):
    import app.services.bot_abstraction as ba
    from app.database import async_session, run_migrations
    from app.models.partner_referral import PartnerReferral
    from worker.tasks.partner_tasks import _check_referral_expiry

    notified = []

    async def fake_notify(manager_id, text):
        notified.append(manager_id)
        return True

    monkeypatch.setattr(ba.bot_layer, "notify_manager", fake_notify)

    await run_migrations()
    async with async_session() as s:
        agency, manager, lead, partner = await _seed(s)
        ref = PartnerReferral(
            agency_id=agency.id, partner_agency_id=partner.id, lead_id=lead.id,
            referred_by_manager_id=manager.id, status="pending",
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        s.add(ref)
        await s.commit()
        ref_id = ref.id

    count = await _check_referral_expiry()
    assert count >= 1

    async with async_session() as s:
        ref = await s.get(PartnerReferral, ref_id)
        assert ref.status == "expired"
    assert notified  # manager notified
