"""Daily subscription check. ТЗ «SaaS-слой» v1, раздел 7."""
from __future__ import annotations

from celery import shared_task

from worker.async_runner import run_async


@shared_task(name="worker.tasks.billing_tasks.check_subscriptions")
def check_subscriptions() -> dict:
    from app.services.billing_admin import check_subscriptions as _check

    return run_async(_check())
