"""Maintenance Celery tasks. TZ section 27.0 (reset_daily_ai_cost).

The logic is split into a plain async function (``_reset_daily_ai_cost``) for
testability and a thin @shared_task wrapper that runs it via run_async().
"""
from __future__ import annotations

import structlog
from celery import shared_task

from app.config import config

from worker.async_runner import run_async

logger = structlog.get_logger()


async def _reset_daily_ai_cost() -> int:
    """Reset the daily AI-cost counters (global + per agency). Returns agency count."""
    from sqlalchemy import select

    from app.database import async_session
    from app.models.agency import Agency
    from app.services.ai_cost_tracker import RedisCostTracker

    tracker = RedisCostTracker(config.redis_url)
    count = 0
    try:
        async with async_session() as session:
            agencies = (await session.execute(select(Agency))).scalars().all()
            for agency in agencies:
                await tracker.reset_daily_cost(str(agency.id))
                count += 1
        await tracker.reset_daily_cost("global")
    finally:
        await tracker.redis.aclose()
    logger.info("Daily AI cost reset", agencies=count)
    return count


@shared_task(name="worker.tasks.maintenance_tasks.reset_daily_ai_cost")
def reset_daily_ai_cost() -> int:
    return run_async(_reset_daily_ai_cost())


# --- Lead urgency decay (TZ 32.2) ------------------------------------------
# Stale leads cool down: hot -> warm after 48h without activity, warm -> cold
# after 7 days. Operates on urgency (not intent_score) per TZ acceptance 35.7.
DECAY_EXCLUDED_STATUSES = ("deal", "rejected", "archived")


async def _decay_lead_scores() -> int:
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from app.database import async_session
    from app.models.lead import Lead

    now = datetime.now(timezone.utc)
    changed = 0
    async with async_session() as session:
        hot = (await session.execute(
            select(Lead).where(
                Lead.urgency == "hot",
                Lead.status.notin_(DECAY_EXCLUDED_STATUSES),
                Lead.updated_at < now - timedelta(hours=48),
            )
        )).scalars().all()
        warm = (await session.execute(
            select(Lead).where(
                Lead.urgency == "warm",
                Lead.status.notin_(DECAY_EXCLUDED_STATUSES),
                Lead.updated_at < now - timedelta(days=7),
            )
        )).scalars().all()
        for lead in hot:
            lead.urgency = "warm"
            changed += 1
        for lead in warm:
            lead.urgency = "cold"
            changed += 1
        await session.commit()
    logger.info("Lead urgency decayed", leads=changed)
    return changed


@shared_task(name="worker.tasks.maintenance_tasks.decay_lead_scores")
def decay_lead_scores() -> int:
    return run_async(_decay_lead_scores())


# --- Overdue lead escalation (TZ 32.3) -------------------------------------
# Hourly: hot leads at 4h -> remind manager, any lead at 24h -> notify owner,
# at 48h -> create an urgent 'escalation' task (once).
# Hours after the last activity at which each step fires. Stored on the lead as
# escalation_stage so the task is idempotent: TZ 32.3 was implemented as three
# one-hour windows (4 <= hrs < 5, ...) evaluated hourly, so a missed run -- a
# deploy, a worker restart, a slow queue -- lost that lead's reminder for good,
# and a double run inside the window pinged the manager twice.
ESCALATION_STEPS = (4, 24, 48)


async def _escalate_overdue_leads() -> int:
    from datetime import datetime, timezone

    from sqlalchemy import select, update

    from app.database import async_session
    from app.models.lead import Lead
    from app.models.manager import Manager
    from app.models.task import Task
    from app.services.bot_abstraction import bot_layer

    now = datetime.now(timezone.utc)
    actions = 0

    async def record(lead, stage: int) -> None:
        """Store the stage without disturbing the idle clock.

        updated_at is what "hours since last activity" is measured from, and the
        mixin bumps it on any write -- so writing the stage through the ORM reset
        the very timer the ladder reads, and the next run saw a fresh lead and
        wound the stage back to zero. Passing updated_at explicitly overrides the
        onupdate default and carries the real activity time forward.
        """
        await session.execute(
            update(Lead).where(Lead.id == lead.id)
            .values(escalation_stage=stage, updated_at=lead.updated_at)
        )
        lead.escalation_stage = stage

    async with async_session() as session:
        leads = (await session.execute(
            select(Lead).where(
                Lead.status.in_(("new", "in_progress")),
                Lead.assigned_to.isnot(None),
            )
        )).scalars().all()

        for lead in leads:
            hrs = (now - lead.updated_at).total_seconds() / 3600
            done = lead.escalation_stage or 0

            # Contact resets the clock (updated_at moves), so the recorded stage
            # has to fall back with it -- otherwise a lead that went quiet again
            # would never escalate a second time.
            if hrs < done:
                await record(lead, 0)
                done = 0

            # Every step now due, oldest first: a lead found at 30 hours after a
            # missed run still gets its 4h and 24h steps rather than skipping them.
            for step in ESCALATION_STEPS:
                if hrs < step or step <= done:
                    continue
                short = str(lead.id)[:6]

                if step == 4:
                    if lead.urgency != "hot":
                        await record(lead, step)
                        continue
                    await bot_layer.notify_manager(
                        str(lead.assigned_to),
                        f"🔔 Горячий лид #{short} без контакта {int(hrs)}ч")
                elif step == 24:
                    owner = (await session.execute(
                        select(Manager).where(
                            Manager.agency_id == lead.agency_id,
                            Manager.role == "owner").limit(1)
                    )).scalar_one_or_none()
                    if owner:
                        await bot_layer.notify_manager(
                            str(owner.id), f"⚠️ Лид #{short} без контакта {int(hrs)}ч.")
                else:
                    existing = (await session.execute(
                        select(Task).where(
                            Task.lead_id == lead.id, Task.task_type == "escalation")
                    )).scalar_one_or_none()
                    if not existing:
                        session.add(Task(
                            agency_id=lead.agency_id, lead_id=lead.id,
                            manager_id=lead.assigned_to, task_type="escalation",
                            title=f"🚨 ПРОСРОЧЕНО 48ч: #{short}",
                            due_at=now, status="pending", is_urgent=True,
                            escalated_at=now,
                        ))

                await record(lead, step)
                actions += 1

        await session.commit()
    logger.info("Overdue leads escalated", actions=actions)
    return actions


@shared_task(name="worker.tasks.maintenance_tasks.escalate_overdue_leads")
def escalate_overdue_leads() -> int:
    return run_async(_escalate_overdue_leads())


# --- Dead source detection (TZ 32.10) --------------------------------------
# Daily: active sources with no signals for 7+ days -> paused + notify owner.
DEAD_SOURCE_DAYS = 7


async def _check_dead_sources() -> int:
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import func, select

    from app.database import async_session
    from app.models.manager import Manager
    from app.models.signal import Signal
    from app.models.source import Source
    from app.services.bot_abstraction import bot_layer

    cutoff = datetime.now(timezone.utc) - timedelta(days=DEAD_SOURCE_DAYS)
    dead: list[Source] = []
    async with async_session() as session:
        active = (await session.execute(
            select(Source).where(Source.status == "active")
        )).scalars().all()
        for src in active:
            last = await session.scalar(
                select(func.max(Signal.created_at)).where(Signal.source_id == src.id))
            if not last or last < cutoff:
                src.status = "paused"
                dead.append(src)
        if dead:
            await session.commit()
            by_agency: dict = {}
            for s in dead:
                by_agency.setdefault(str(s.agency_id), []).append(s.source_name or str(s.id)[:8])
            for aid, names in by_agency.items():
                owner = (await session.execute(
                    select(Manager).where(
                        Manager.agency_id == aid,
                        Manager.role.in_(("owner", "admin"))).limit(1)
                )).scalar_one_or_none()
                if owner:
                    names_fmt = "\n".join(f"• {n}" for n in names[:10])
                    await bot_layer.notify_manager(
                        str(owner.id),
                        f"🔇 Источники без сигналов 7+ дней → приостановлены:\n{names_fmt}")
    logger.info("Dead sources paused", sources=len(dead))
    return len(dead)


@shared_task(name="worker.tasks.maintenance_tasks.check_dead_sources")
def check_dead_sources() -> int:
    return run_async(_check_dead_sources())


# --- Celery queue depth alert (TZ 24) --------------------------------------
# Every few minutes: if the pending backlog on the default queue exceeds the
# threshold, fire a critical alert so a stuck/overloaded worker is noticed.
QUEUE_ALERT_THRESHOLD = 50


async def _check_queue_depth() -> int:
    import redis.asyncio as aioredis

    from app.services.alerts import send_critical_alert

    client = aioredis.from_url(config.redis_url, socket_connect_timeout=2, socket_timeout=2)
    try:
        depth = int(await client.llen("celery"))
    finally:
        await client.aclose()
    if depth > QUEUE_ALERT_THRESHOLD:
        await send_critical_alert(f"Очередь Celery перегружена: {depth} задач в ожидании")
        logger.warning("Celery queue backlog high", depth=depth)
    return depth


@shared_task(name="worker.tasks.maintenance_tasks.check_queue_depth")
def check_queue_depth() -> int:
    return run_async(_check_queue_depth())
