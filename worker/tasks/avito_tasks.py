"""Celery: catalogue sync from Avito. ТЗ «Avito + фильтрация» v1, блок 1.9."""
from __future__ import annotations

from celery import shared_task

from worker.async_runner import run_async


@shared_task(name="worker.tasks.avito_tasks.sync_avito")
def sync_avito() -> dict:
    """Every agency with an Avito account; idempotent, safe to rerun."""
    from app.services.avito_sync import sync_all

    return run_async(sync_all())
