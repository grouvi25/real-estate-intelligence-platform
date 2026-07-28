"""Manager task list router. TZ section 30 (screen `/tasks`).

Tasks are produced by SLA escalation (worker/tasks/maintenance_tasks.py) and by
the sell-to-buy flow (app/services/alternative_lead.py), and the dashboard shows
a count of urgent ones -- but until now nothing could list, claim or close them,
so the whole "manager gets a task and works it" loop dead-ended in the database.

Manager-scoped: the agency always comes from the JWT, never from client input.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, or_, select

from app.database import get_session
from app.dependencies import CurrentManager, get_current_manager
from app.exceptions import NotFoundError, ValidationError
from app.models.lead import Lead
from app.models.task import Task

logger = structlog.get_logger()
router = APIRouter()

# migrations/001_init.sql: tasks.status CHECK
VALID_STATUSES = {"pending", "done", "overdue", "cancelled"}
# Statuses a manager may set from the UI ("overdue" is set by the escalation job).
SETTABLE_STATUSES = {"done", "cancelled", "pending"}
MAX_PAGE = 200


class UpdateTaskRequest(BaseModel):
    status: Optional[str] = None
    # Claim the task for the calling manager (or hand it back with false).
    assign_to_me: Optional[bool] = None


def _task_dto(t: Task, lead: Optional[Lead] = None) -> dict:
    overdue = bool(
        t.due_at and t.status == "pending" and t.due_at < datetime.now(timezone.utc)
    )
    return {
        "id": str(t.id),
        "task_type": t.task_type,
        "title": t.title,
        "description": t.description,
        "suggested_message": t.suggested_message,
        "status": t.status,
        "is_urgent": bool(t.is_urgent),
        "is_overdue": overdue,
        "due_at": t.due_at.isoformat() if t.due_at else None,
        "completed_at": t.completed_at.isoformat() if t.completed_at else None,
        "escalated_at": t.escalated_at.isoformat() if t.escalated_at else None,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "lead_id": str(t.lead_id) if t.lead_id else None,
        "manager_id": str(t.manager_id) if t.manager_id else None,
        "lead_name": (lead.name if lead else None),
        "lead_urgency": (lead.urgency if lead else None),
    }


@router.get("")
async def list_tasks(
    status: str = "pending",
    only_mine: bool = False,
    only_urgent: bool = False,
    limit: int = 50,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """List agency tasks, most urgent and soonest-due first."""
    limit = min(max(limit, 1), MAX_PAGE)
    if status != "all" and status not in VALID_STATUSES:
        raise ValidationError("status", f"недопустимый статус: {status}")

    stmt = select(Task).where(Task.agency_id == uuid.UUID(current.agency_id))
    if status != "all":
        stmt = stmt.where(Task.status == status)
    if only_mine:
        stmt = stmt.where(Task.manager_id == uuid.UUID(current.manager_id))
    if only_urgent:
        stmt = stmt.where(Task.is_urgent.is_(True))

    # Unassigned tasks sort with the rest; due_at NULLs last so dated work leads.
    stmt = stmt.order_by(
        Task.is_urgent.desc(), Task.due_at.asc().nullslast(), Task.created_at.desc()
    ).limit(limit)

    tasks = (await session.execute(stmt)).scalars().all()

    lead_ids = {t.lead_id for t in tasks if t.lead_id}
    leads: dict[uuid.UUID, Lead] = {}
    if lead_ids:
        rows = (await session.execute(select(Lead).where(Lead.id.in_(lead_ids)))).scalars().all()
        leads = {lead.id: lead for lead in rows}

    return {
        "tasks": [_task_dto(t, leads.get(t.lead_id)) for t in tasks],
        "count": len(tasks),
    }


@router.get("/summary")
async def tasks_summary(
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """Counters for the dashboard: open / urgent / overdue."""
    agency_id = uuid.UUID(current.agency_id)
    now = datetime.now(timezone.utc)

    pending = select(func.count()).select_from(Task).where(
        Task.agency_id == agency_id, Task.status == "pending"
    )
    urgent = pending.where(Task.is_urgent.is_(True))
    overdue = select(func.count()).select_from(Task).where(
        Task.agency_id == agency_id,
        or_(Task.status == "overdue", (Task.status == "pending") & (Task.due_at < now)),
    )

    return {
        "pending": await session.scalar(pending) or 0,
        "urgent": await session.scalar(urgent) or 0,
        "overdue": await session.scalar(overdue) or 0,
    }


@router.get("/{task_id}")
async def get_task(
    task_id: uuid.UUID,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    task = await session.get(Task, task_id)
    if task is None or str(task.agency_id) != current.agency_id:
        raise NotFoundError("Task", str(task_id))
    lead = await session.get(Lead, task.lead_id) if task.lead_id else None
    return _task_dto(task, lead)


@router.patch("/{task_id}")
async def update_task(
    task_id: uuid.UUID,
    req: UpdateTaskRequest,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """Close, cancel, reopen or claim a task."""
    task = await session.get(Task, task_id)
    if task is None or str(task.agency_id) != current.agency_id:
        raise NotFoundError("Task", str(task_id))

    if req.status is not None:
        if req.status not in SETTABLE_STATUSES:
            raise ValidationError("status", f"недопустимый статус: {req.status}")
        task.status = req.status
        # Closing stamps completion; reopening clears it so the SLA job can pick
        # the task up again.
        task.completed_at = datetime.now(timezone.utc) if req.status == "done" else None

    if req.assign_to_me is not None:
        task.manager_id = uuid.UUID(current.manager_id) if req.assign_to_me else None

    await session.commit()
    logger.info(
        "Task updated", task_id=str(task_id), status=task.status, manager_id=str(task.manager_id)
    )

    lead = await session.get(Lead, task.lead_id) if task.lead_id else None
    return _task_dto(task, lead)
