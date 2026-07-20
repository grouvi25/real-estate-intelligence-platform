"""Celery application + beat schedule. TZ section 11.1.

Celery has no native async task support in the stable branch, so tasks use
asyncio.run() internally (see worker/tasks/*). For production the gevent pool is
used (see docker-compose command).

Beat schedule note: only tasks that are actually implemented are scheduled here.
The remaining entries from TZ 11.1 are listed below and enabled as their task
modules land (avoids "Received unregistered task" errors on a live worker).
"""
from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.config import config

celery_app = Celery(
    "real_estate_intelligence",
    broker=config.redis_url,
    backend=config.redis_url,
    broker_connection_retry_on_startup=True,
    include=[
        "worker.tasks.maintenance_tasks",
        "worker.tasks.geo_tasks",
        "worker.tasks.matching_tasks",
        "worker.tasks.source_tasks",
        "worker.tasks.partner_tasks",
        "worker.tasks.knowledge_tasks",
        "worker.tasks.crm_tasks",
        "worker.tasks.report_tasks",
        "worker.tasks.collector_tasks",
        "worker.tasks.signal_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Europe/Moscow",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,
    worker_prefetch_multiplier=1,
)

# --- Beat schedule (enabled entries only) ---
celery_app.conf.beat_schedule = {
    "ai-cost-daily-reset": {
        "task": "worker.tasks.maintenance_tasks.reset_daily_ai_cost",
        "schedule": crontab(hour=0, minute=1),  # 00:01 daily
    },
    "geo-discovery-weekly": {
        "task": "worker.tasks.source_tasks.geo_discovery_cron",
        "schedule": crontab(hour=2, minute=0, day_of_week=1),  # Mon 02:00 MSK
    },
    "check-referral-expiry": {
        "task": "worker.tasks.partner_tasks.check_referral_expiry",
        "schedule": crontab(hour=9, minute=0),  # 09:00 daily
    },
    "knowledge-moat-update": {
        "task": "worker.tasks.knowledge_tasks.update_knowledge_moat",
        "schedule": crontab(hour=3, minute=0, day_of_week=0),  # Sun 03:00 MSK
    },
    "lead-score-decay": {
        "task": "worker.tasks.maintenance_tasks.decay_lead_scores",
        "schedule": crontab(hour="*/12", minute=15),  # every 12h
    },
    "escalate-overdue-leads": {
        "task": "worker.tasks.maintenance_tasks.escalate_overdue_leads",
        "schedule": crontab(minute=0),  # hourly
    },
    "dead-source-check": {
        "task": "worker.tasks.maintenance_tasks.check_dead_sources",
        "schedule": crontab(hour=6, minute=0),  # 06:00 daily
    },
    "daily-report": {
        "task": "worker.tasks.report_tasks.generate_daily_report",
        "schedule": crontab(hour=7, minute=30),  # 07:30 MSK
    },
    "queue-depth-check": {
        "task": "worker.tasks.maintenance_tasks.check_queue_depth",
        "schedule": crontab(minute="*/5"),  # every 5 min
    },
    "collect-telegram-sources": {
        "task": "worker.tasks.collector_tasks.collect_telegram_sources",
        "schedule": crontab(minute="*/10"),  # every 10 min (no-op without Telethon)
    },
    "intent-scoring-batch": {
        "task": "worker.tasks.signal_tasks.score_intent_batch",
        "schedule": crontab(minute="*/5"),  # every 5 min (no-op without AI keys)
    },
}

# --- Planned schedule from TZ 11.1 (all core periodic tasks now implemented) ---
# rematch_on_price_change is triggered on demand from the property PATCH endpoint
# (worker.tasks.matching_tasks.rematch_on_price_change), not on a fixed schedule.
