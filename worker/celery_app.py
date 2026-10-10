"""Celery application + beat schedule. TZ section 11.1.

Celery has no native async task support in the stable branch, so tasks hand
their coroutines to worker.async_runner.run_async(), which owns a single
long-lived event loop per worker process. The worker runs on the threads pool
(see docker-compose command): the previous gevent pool ran every greenlet in one
OS thread, where overlapping asyncio.run() calls raised "cannot be called from a
running event loop" and killed ~2 of every 3 scheduled tasks.

Beat schedule note: only tasks that are actually implemented are scheduled here.
The remaining entries from TZ 11.1 are listed below and enabled as their task
modules land (avoids "Received unregistered task" errors on a live worker).
"""
from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.config import config
from app.logging_config import quiet_secret_bearing_loggers

quiet_secret_bearing_loggers()

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
        "worker.tasks.billing_tasks",
        "worker.tasks.avito_tasks",
        "worker.tasks.bot_tasks",
        "worker.tasks.topnlab_sync",
        "worker.tasks.discovery",
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
    # ТЗ «Сигналы» 5: discovery has its own queue so a slow search never holds up
    # collection and scoring. The worker consumes both (docker-compose: -Q).
    task_routes={
        "worker.tasks.discovery.*": {"queue": "discovery"},
        "worker.tasks.source_tasks.*": {"queue": "discovery"},
    },
)

# --- Beat schedule (enabled entries only) ---
celery_app.conf.beat_schedule = {
    "ai-cost-daily-reset": {
        "task": "worker.tasks.maintenance_tasks.reset_daily_ai_cost",
        "schedule": crontab(hour=0, minute=1),  # 00:01 daily
    },
    # ТЗ «Сигналы» v1.0, раздел 5. Replaces the weekly geo_discovery_cron: the
    # search now runs every hour, a few queries at a time.
    "discovery-hourly": {
        "task": "worker.tasks.discovery.run_discovery_for_all_agencies",
        "schedule": crontab(minute=15),
    },
    "source-health-check": {
        "task": "worker.tasks.discovery.check_source_health",
        "schedule": crontab(minute=45),
    },
    "discovery-sandbox-retry": {
        "task": "worker.tasks.discovery.retry_sandbox_candidates",
        "schedule": crontab(hour=4, minute=30),
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
    "collect-vk-sources": {
        "task": "worker.tasks.collector_tasks.collect_vk_sources",
        # Offset from the Telegram run so the two do not contend for the worker.
        "schedule": crontab(minute="5-59/10"),  # every 10 min (no-op without VK token)
    },
    "price-drop-sweep": {
        # TZ 11.1 has this on a schedule; the PATCH endpoint covers the common
        # case instantly, and this catches prices changed outside the API.
        "task": "worker.tasks.matching_tasks.sweep_price_drops",
        "schedule": crontab(hour=4, minute=20),  # 04:20 MSK daily
    },
    "collect-web-sources": {
        # Feeds and YouTube move far slower than chats; hourly is plenty and
        # keeps well inside the YouTube daily quota.
        "task": "worker.tasks.collector_tasks.collect_web_sources",
        "schedule": crontab(minute=35),  # hourly
    },
    "billing-subscription-check": {
        "task": "worker.tasks.billing_tasks.check_subscriptions",
        "schedule": crontab(hour=9, minute=0),  # 09:00 MSK daily (ТЗ «SaaS-слой» 7.2)
    },
    "avito-property-sync": {
        "task": "worker.tasks.avito_tasks.sync_avito",
        # ТЗ 1.10: every N minutes. A no-op for agencies without an Avito account.
        "schedule": max(config.avito_sync_interval_minutes, 10) * 60,
    },
    "bot-conversation-timeouts": {
        "task": "worker.tasks.bot_tasks.pause_quiet_conversations",
        "schedule": crontab(minute="*/10"),  # ТЗ: 30 min of silence -> silent
    },
    "bot-conversation-reminders": {
        "task": "worker.tasks.bot_tasks.send_conversation_reminders",
        "schedule": crontab(minute=30),  # hourly: BOT_REMINDER_HOURS after, one reminder
    },
    "bot-learning-pool-update": {
        "task": "worker.tasks.bot_tasks.update_bot_learning_pool",
        "schedule": crontab(hour=4, minute=0, day_of_week=0),  # Sun 04:00 MSK
    },
    "intent-scoring-batch": {
        "task": "worker.tasks.signal_tasks.score_intent_batch",
        "schedule": crontab(minute="*/5"),  # every 5 min (no-op without AI keys)
    },
}

# --- Planned schedule from TZ 11.1 (all core periodic tasks now implemented) ---
# rematch_on_price_change is triggered on demand from the property PATCH endpoint
# (worker.tasks.matching_tasks.rematch_on_price_change), not on a fixed schedule.
