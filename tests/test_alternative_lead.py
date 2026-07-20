"""Alternative (sell-to-buy) lead tests."""
import os
import uuid
from types import SimpleNamespace

import pytest


def test_build_alternative_tasks_uses_target_budget():
    from app.services.alternative_lead import build_alternative_tasks

    lead = SimpleNamespace(
        agency_id=uuid.uuid4(), id=uuid.uuid4(), assigned_to=None, budget_max=8_000_000,
        alternative_seller_data={"target_purchase_budget": 6_000_000, "address": "ул. X", "value": 5_000_000},
    )
    tasks, target = build_alternative_tasks(lead)
    assert target == 6_000_000
    assert [t.task_type for t in tasks] == ["alternative_sell", "alternative_buy"]


def test_build_alternative_tasks_falls_back_to_budget_max():
    from app.services.alternative_lead import build_alternative_tasks

    lead = SimpleNamespace(
        agency_id=uuid.uuid4(), id=uuid.uuid4(), assigned_to=None, budget_max=7_000_000,
        alternative_seller_data=None,
    )
    tasks, target = build_alternative_tasks(lead)
    assert target == 7_000_000
    assert len(tasks) == 2


@pytest.mark.skipif(os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL")
@pytest.mark.asyncio
async def test_process_alternative_endpoint(monkeypatch):
    import worker.tasks.matching_tasks as mt
    from sqlalchemy import select

    from app.database import async_session, run_migrations
    from app.dependencies import CurrentManager
    from app.exceptions import ValidationError
    from app.models.agency import Agency
    from app.models.lead import Lead
    from app.models.task import Task
    from app.routers.leads import process_alternative

    enqueued = []
    monkeypatch.setattr(mt.run_matching_for_lead, "delay", lambda *a, **k: enqueued.append(a))

    await run_migrations()
    async with async_session() as s:
        agency = Agency(name="Alt Agency", base_city="Геленджик")
        s.add(agency)
        await s.flush()
        alt_lead = Lead(agency_id=agency.id, source_type="manual", lead_type="alternative",
                        budget_max=8_000_000, alternative_seller_data={"target_purchase_budget": 6_000_000},
                        status="new")
        s.add(alt_lead)
        normal_lead = Lead(agency_id=agency.id, source_type="signal", lead_type="buyer", status="new")
        s.add(normal_lead)
        await s.commit()
        agency_id, alt_id, normal_id = agency.id, alt_lead.id, normal_lead.id

    current = CurrentManager(manager_id="m1", agency_id=str(agency_id))
    async with async_session() as s:
        resp = await process_alternative(alt_id, current=current, session=s)
    assert resp["tasks_created"] == 2
    assert resp["target_budget"] == 6_000_000
    assert enqueued and enqueued[0] == (str(alt_id), 6_000_000)

    async with async_session() as s:
        tasks = (await s.execute(select(Task).where(Task.lead_id == alt_id))).scalars().all()
        assert sorted(t.task_type for t in tasks) == ["alternative_buy", "alternative_sell"]

    # A non-alternative lead is rejected.
    async with async_session() as s:
        with pytest.raises(ValidationError):
            await process_alternative(normal_id, current=current, session=s)
