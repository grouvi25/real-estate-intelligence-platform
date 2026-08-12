"""SLA escalation must survive a missed run. TZ 32.3 (needs PostgreSQL).

The original implementation compared the elapsed hours against three one-hour
windows (4 <= hrs < 5, 24 <= hrs < 25, 48 <= hrs < 49) inside an hourly task. A
run that never happened -- a deploy, a worker restart, a slow queue -- dropped
that lead's reminder for good, and two runs inside one window pinged the manager
twice. Neither shows up as an error anywhere.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from tests.helpers import unique_telegram_id

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL"
)


class _Bot:
    def __init__(self):
        self.sent = []

    async def notify_manager(self, manager_id, text):
        self.sent.append((manager_id, text))
        return True


@pytest.fixture
def bot(monkeypatch):
    import app.services.bot_abstraction as ba

    rec = _Bot()
    monkeypatch.setattr(ba, "bot_layer", rec)
    return rec


async def _lead(s, *, hours_idle: float, urgency: str = "hot", stage: int = 0):
    from app.models.agency import Agency
    from app.models.lead import Lead
    from app.models.manager import Manager

    agency = Agency(name=f"Esc {uuid.uuid4().hex[:6]}", base_city="Геленджик")
    s.add(agency)
    await s.flush()
    manager = Manager(agency_id=agency.id, name="Менеджер", role="owner",
                      telegram_id=unique_telegram_id(), is_active=True)
    s.add(manager)
    await s.flush()

    lead = Lead(agency_id=agency.id, source_type="signal", status="new",
                urgency=urgency, assigned_to=manager.id, escalation_stage=stage)
    s.add(lead)
    await s.flush()
    # updated_at is maintained by the ORM, so it is set explicitly here.
    lead.updated_at = datetime.now(timezone.utc) - timedelta(hours=hours_idle)
    await s.commit()
    return lead


@pytest.mark.asyncio
async def test_a_lead_found_late_still_gets_every_step(bot):
    """The point of the change: 30 hours idle after a missed run must produce the
    4h and 24h steps, not skip straight past them."""
    from app.database import async_session, run_migrations
    from app.models.lead import Lead
    from worker.tasks.maintenance_tasks import _escalate_overdue_leads

    await run_migrations()
    async with async_session() as s:
        lead = await _lead(s, hours_idle=30)
        lead_id = lead.id

    await _escalate_overdue_leads()

    async with async_session() as s:
        lead = await s.get(Lead, lead_id)
    assert lead.escalation_stage == 24, "оба пропущенных шага должны отработать за один проход"
    assert any(str(lead_id)[:6] in text for _, text in bot.sent)


@pytest.mark.asyncio
async def test_running_twice_does_not_notify_twice(bot):
    from app.database import async_session, run_migrations
    from worker.tasks.maintenance_tasks import _escalate_overdue_leads

    await run_migrations()
    async with async_session() as s:
        await _lead(s, hours_idle=5)

    await _escalate_overdue_leads()
    before = len(bot.sent)
    await _escalate_overdue_leads()

    assert len(bot.sent) == before, "повторный запуск не должен слать уведомление снова"


@pytest.mark.asyncio
async def test_a_lead_inside_the_sla_is_left_alone(bot):
    from app.database import async_session, run_migrations
    from app.models.lead import Lead
    from worker.tasks.maintenance_tasks import _escalate_overdue_leads

    await run_migrations()
    async with async_session() as s:
        lead = await _lead(s, hours_idle=1)
        lead_id = lead.id

    await _escalate_overdue_leads()

    async with async_session() as s:
        lead = await s.get(Lead, lead_id)
    assert lead.escalation_stage == 0
    assert not any(str(lead_id)[:6] in text for _, text in bot.sent)


@pytest.mark.asyncio
async def test_contact_does_not_rewind_lifetime_escalation(bot):
    """A completed escalation step is emitted at most once in the lead lifetime."""
    from app.database import async_session, run_migrations
    from app.models.lead import Lead
    from worker.tasks.maintenance_tasks import _escalate_overdue_leads

    await run_migrations()
    async with async_session() as s:
        # Escalated to 24 previously, but contacted an hour ago.
        lead = await _lead(s, hours_idle=1, stage=24)
        lead_id = lead.id

    await _escalate_overdue_leads()

    async with async_session() as s:
        lead = await s.get(Lead, lead_id)
    assert lead.escalation_stage == 24, "после контакта лестница должна сброситься"


@pytest.mark.asyncio
async def test_recording_a_step_does_not_reset_the_idle_clock(bot):
    """updated_at is the clock the ladder reads, and the ORM bumps it on any
    write -- so storing the stage through the ORM reset the timer, and the next
    run saw a fresh lead and wound the stage back to zero."""
    from app.database import async_session, run_migrations
    from app.models.lead import Lead
    from worker.tasks.maintenance_tasks import _escalate_overdue_leads

    await run_migrations()
    async with async_session() as s:
        lead = await _lead(s, hours_idle=50)
        lead_id, idle_at = lead.id, lead.updated_at

    await _escalate_overdue_leads()
    await _escalate_overdue_leads()

    async with async_session() as s:
        lead = await s.get(Lead, lead_id)
    assert lead.escalation_stage == 48
    assert lead.updated_at == idle_at, "эскалация не должна двигать отметку активности"


@pytest.mark.asyncio
async def test_the_48h_step_creates_one_urgent_task(bot):
    from app.database import async_session, run_migrations
    from app.models.lead import Lead
    from app.models.task import Task
    from sqlalchemy import func, select
    from worker.tasks.maintenance_tasks import _escalate_overdue_leads

    await run_migrations()
    async with async_session() as s:
        lead = await _lead(s, hours_idle=50)
        lead_id = lead.id

    await _escalate_overdue_leads()
    await _escalate_overdue_leads()

    async with async_session() as s:
        count = await s.scalar(
            select(func.count()).select_from(Task).where(
                Task.lead_id == lead_id, Task.task_type == "escalation")
        )
        task = (await s.execute(
            select(Task).where(Task.lead_id == lead_id))).scalars().first()
        lead = await s.get(Lead, lead_id)
    assert count == 1
    assert task.is_urgent is True
    assert lead.escalation_stage == 48


@pytest.mark.asyncio
async def test_a_cold_lead_skips_the_4h_ping_but_still_advances(bot):
    """Only hot leads get the 4h nudge; the stage must still move so the lead is
    not re-examined for it on every run."""
    from app.database import async_session, run_migrations
    from app.models.lead import Lead
    from worker.tasks.maintenance_tasks import _escalate_overdue_leads

    await run_migrations()
    async with async_session() as s:
        lead = await _lead(s, hours_idle=5, urgency="cold")
        lead_id = lead.id

    await _escalate_overdue_leads()

    async with async_session() as s:
        lead = await s.get(Lead, lead_id)
    assert lead.escalation_stage == 4
    assert not any(str(lead_id)[:6] in text for _, text in bot.sent)


@pytest.mark.asyncio
async def test_one_lead_with_two_escalation_tasks_does_not_stop_the_sweep(bot):
    """The whole run used to die on a single duplicate row.

    Nothing in the schema stops a lead from having two escalation tasks — two
    overlapping beat runs are enough. The existence check asked for exactly one
    row, so the second one raised, the exception escaped before the commit, and
    every lead in that run lost its update. SLA escalation would have been dead
    for every agency, on every run, with nothing in the product looking broken.
    """
    from sqlalchemy import func, select

    from app.database import async_session, run_migrations
    from app.models.lead import Lead
    from app.models.task import Task
    from worker.tasks.maintenance_tasks import _escalate_overdue_leads

    await run_migrations()
    async with async_session() as s:
        broken = await _lead(s, hours_idle=50)
        for _ in range(2):
            s.add(Task(agency_id=broken.agency_id, lead_id=broken.id,
                       manager_id=broken.assigned_to, task_type="escalation",
                       title="дубль", status="pending"))
        healthy = await _lead(s, hours_idle=5)
        broken_id, healthy_id = broken.id, healthy.id
        await s.commit()

    await _escalate_overdue_leads()

    async with async_session() as s:
        healthy = await s.get(Lead, healthy_id)
        broken = await s.get(Lead, broken_id)

    # The neighbour still advanced — that is the whole point.
    assert healthy.escalation_stage == 4
    # And the duplicate did not silently gain a third task.
    async with async_session() as s:
        count = await s.scalar(
            select(func.count()).select_from(Task).where(
                Task.lead_id == broken_id, Task.task_type == "escalation"))
    assert count == 2
