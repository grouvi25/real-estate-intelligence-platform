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
}

# --- Planned schedule from TZ 11.1 (enable as each task is implemented) ---
# "intent-scoring-batch":   worker.tasks.signal_tasks.score_intent_batch        every 5 min
# "daily-report":           worker.tasks.report_tasks.generate_daily_report     07:30 MSK
# "knowledge-moat-update":  worker.tasks.knowledge_tasks.update_knowledge_moat   Sun 03:00
# "check-referral-expiry":  worker.tasks.partner_tasks.check_referral_expiry     09:00
# "geo-discovery-weekly":   worker.tasks.source_tasks.geo_discovery_cron         Mon 02:00
# "lead-score-decay":       worker.tasks.maintenance_tasks.decay_lead_scores     every 12h
# "dead-source-check":      worker.tasks.maintenance_tasks.check_dead_sources    06:00
# "price-change-rematch":   worker.tasks.matching_tasks.rematch_on_price_change  every 2h
# "escalate-overdue-leads": worker.tasks.maintenance_tasks.escalate_overdue_leads hourly
