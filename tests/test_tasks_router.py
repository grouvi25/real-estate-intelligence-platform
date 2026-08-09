"""Manager task list endpoint tests (need PostgreSQL). TZ 30 screen `/tasks`.

Escalation and the sell-to-buy flow have always created Task rows; until this
router there was no way to read or close them, so the loop dead-ended in the DB.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from tests.helpers import unique_telegram_id

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL"
)


async def _fixture(s, *, urgent_due=None):
    """Agency + manager + lead + two tasks (one urgent, one plain)."""
    from app.models.agency import Agency
    from app.models.lead import Lead
    from app.models.manager import Manager
    from app.models.task import Task

    agency = Agency(name="Tasks Agency", base_city="Геленджик")
    s.add(agency)
    await s.flush()

    manager = Manager(agency_id=agency.id, name="Менеджер", telegram_id=unique_telegram_id())
    lead = Lead(agency_id=agency.id, source_type="signal", urgency="hot")
    lead.name = "Иван"
    s.add_all([manager, lead])
    await s.flush()

    urgent = Task(
        agency_id=agency.id, lead_id=lead.id, task_type="escalation",
        title="Срочно связаться", status="pending", is_urgent=True,
        due_at=urgent_due or datetime.now(timezone.utc) - timedelta(hours=2),
    )
    plain = Task(
        agency_id=agency.id, lead_id=lead.id, task_type="follow_up",
        title="Перезвонить завтра", status="pending", is_urgent=False,
        due_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    s.add_all([urgent, plain])
    await s.commit()
    return agency, manager, lead, urgent, plain


@pytest.mark.asyncio
async def test_list_returns_agency_tasks_urgent_first():
    from app.database import async_session, run_migrations
    from app.dependencies import CurrentManager
    from app.routers.tasks import list_tasks

    await run_migrations()
    async with async_session() as s:
        agency, manager, lead, urgent, _ = await _fixture(s)
        current = CurrentManager(manager_id=str(manager.id), agency_id=str(agency.id))

    async with async_session() as s:
        res = await list_tasks(current=current, session=s)

    assert res["count"] == 2
    assert res["tasks"][0]["id"] == str(urgent.id)
    assert res["tasks"][0]["is_urgent"] is True
    assert res["tasks"][0]["is_overdue"] is True  # due_at in the past
    assert res["tasks"][0]["lead_name"] == "Иван"  # PII decrypted for the card


@pytest.mark.asyncio
async def test_tasks_are_scoped_to_the_token_agency():
    """A manager must never see another agency's tasks."""
    from app.database import async_session, run_migrations
    from app.dependencies import CurrentManager
    from app.models.agency import Agency
    from app.routers.tasks import list_tasks

    await run_migrations()
    async with async_session() as s:
        await _fixture(s)
        other = Agency(name="Other Agency", base_city="Сочи")
        s.add(other)
        await s.commit()
        current = CurrentManager(manager_id=str(uuid.uuid4()), agency_id=str(other.id))

    async with async_session() as s:
        res = await list_tasks(current=current, session=s)

    assert res["count"] == 0


@pytest.mark.asyncio
async def test_only_urgent_and_only_mine_filters():
    from app.database import async_session, run_migrations
    from app.dependencies import CurrentManager
    from app.routers.tasks import UpdateTaskRequest, list_tasks, update_task

    await run_migrations()
    async with async_session() as s:
        agency, manager, _, urgent, _ = await _fixture(s)
        current = CurrentManager(manager_id=str(manager.id), agency_id=str(agency.id))

    async with async_session() as s:
        res = await list_tasks(only_urgent=True, current=current, session=s)
        assert res["count"] == 1 and res["tasks"][0]["id"] == str(urgent.id)

        # Nothing is assigned yet.
        assert (await list_tasks(only_mine=True, current=current, session=s))["count"] == 0
        await update_task(urgent.id, UpdateTaskRequest(assign_to_me=True),
                          current=current, session=s)

    async with async_session() as s:
        mine = await list_tasks(only_mine=True, current=current, session=s)
        assert mine["count"] == 1
        assert mine["tasks"][0]["manager_id"] == str(manager.id)


@pytest.mark.asyncio
async def test_complete_and_reopen_a_task():
    from app.database import async_session, run_migrations
    from app.dependencies import CurrentManager
    from app.routers.tasks import UpdateTaskRequest, list_tasks, update_task

    await run_migrations()
    async with async_session() as s:
        agency, manager, _, urgent, _ = await _fixture(s)
        current = CurrentManager(manager_id=str(manager.id), agency_id=str(agency.id))

    async with async_session() as s:
        done = await update_task(urgent.id, UpdateTaskRequest(status="done"),
                                 current=current, session=s)
        assert done["status"] == "done"
        assert done["completed_at"] is not None
        # A closed task is out of the default (pending) list.
        assert all(t["id"] != str(urgent.id)
                   for t in (await list_tasks(current=current, session=s))["tasks"])

        reopened = await update_task(urgent.id, UpdateTaskRequest(status="pending"),
                                     current=current, session=s)
        assert reopened["status"] == "pending"
        # Cleared so the SLA job can pick it up again.
        assert reopened["completed_at"] is None


@pytest.mark.asyncio
async def test_summary_counts_pending_urgent_overdue():
    from app.database import async_session, run_migrations
    from app.dependencies import CurrentManager
    from app.routers.tasks import tasks_summary

    await run_migrations()
    async with async_session() as s:
        agency, manager, *_ = await _fixture(s)
        current = CurrentManager(manager_id=str(manager.id), agency_id=str(agency.id))

    async with async_session() as s:
        res = await tasks_summary(current=current, session=s)

    assert res["pending"] == 2
    assert res["urgent"] == 1
    assert res["overdue"] == 1


@pytest.mark.asyncio
async def test_rejects_unknown_status_and_foreign_task():
    from app.database import async_session, run_migrations
    from app.dependencies import CurrentManager
    from app.exceptions import NotFoundError, ValidationError
    from app.routers.tasks import UpdateTaskRequest, list_tasks, update_task

    await run_migrations()
    async with async_session() as s:
        agency, manager, _, urgent, _ = await _fixture(s)
        current = CurrentManager(manager_id=str(manager.id), agency_id=str(agency.id))
        stranger = CurrentManager(manager_id=str(uuid.uuid4()), agency_id=str(uuid.uuid4()))

    async with async_session() as s:
        with pytest.raises(ValidationError):
            await list_tasks(status="nonsense", current=current, session=s)
        with pytest.raises(ValidationError):
            await update_task(urgent.id, UpdateTaskRequest(status="overdue"),
                              current=current, session=s)
        with pytest.raises(NotFoundError):
            await update_task(urgent.id, UpdateTaskRequest(status="done"),
                              current=stranger, session=s)
