"""Alternative (sell-to-buy) lead logic. TZ section 22.1.

An "alternative" buyer must first sell their current property, then buy within a
target budget. We create two manager tasks and (via the caller) re-run matching
against the target purchase budget.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional


def build_alternative_tasks(lead: Any) -> tuple[list, Optional[int]]:
    """Build the sell + buy tasks for an alternative lead.

    Returns (tasks, target_budget). Tasks are transient ORM objects; the caller
    adds them to a session and commits.
    """
    from app.models.task import Task

    seller = lead.alternative_seller_data or {}
    target_budget = seller.get("target_purchase_budget") or lead.budget_max
    due = datetime.now(timezone.utc) + timedelta(hours=48)

    sell_task = Task(
        agency_id=lead.agency_id,
        lead_id=lead.id,
        manager_id=lead.assigned_to,
        task_type="alternative_sell",
        title="Альтернативщик: оценить и выставить текущую квартиру",
        description=f"Адрес: {seller.get('address', 'N/A')}; Оценка: {seller.get('value')}",
        due_at=due,
        status="pending",
    )
    buy_task = Task(
        agency_id=lead.agency_id,
        lead_id=lead.id,
        manager_id=lead.assigned_to,
        task_type="alternative_buy",
        title=f"Подбор объекта на целевой бюджет {target_budget}",
        due_at=due,
        status="pending",
    )
    return [sell_task, buy_task], target_budget
