"""Maintenance Celery tasks. TZ section 27.0 (reset_daily_ai_cost).

The logic is split into a plain async function (``_reset_daily_ai_cost``) for
testability and a thin @shared_task wrapper that runs it via asyncio.run().
"""
from __future__ import annotations

import asyncio

import structlog
from celery import shared_task

from app.config import config

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
    return asyncio.run(_reset_daily_ai_cost())


# --- Lead score decay (TZ 32) ----------------------------------------------
# Stale, un-progressed leads slowly lose intent score so dashboards stay honest
# and the hottest *fresh* leads bubble up.
DECAY_AFTER_DAYS = 3
DECAY_FACTOR = 0.85
ACTIVE_LEAD_STATUSES = ("new", "contacted", "qualifying")


async def _decay_lead_scores() -> int:
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from app.database import async_session
    from app.models.lead import Lead

    cutoff = datetime.now(timezone.utc) - timedelta(days=DECAY_AFTER_DAYS)
    changed = 0
    async with async_session() as session:
        stmt = select(Lead).where(
            Lead.status.in_(ACTIVE_LEAD_STATUSES),
            Lead.intent_score.isnot(None),
            Lead.intent_score > 0,
            Lead.updated_at < cutoff,
        )
        for lead in (await session.execute(stmt)).scalars().all():
            new_score = int(lead.intent_score * DECAY_FACTOR)
            if new_score != lead.intent_score:
                lead.intent_score = new_score
                changed += 1
        await session.commit()
    logger.info("Lead scores decayed", leads=changed)
    return changed


@shared_task(name="worker.tasks.maintenance_tasks.decay_lead_scores")
def decay_lead_scores() -> int:
    return asyncio.run(_decay_lead_scores())


# --- Overdue lead escalation (TZ 32) ---------------------------------------
# A pending contact task whose due time has passed (or that has aged past the
# SLA) is flagged urgent so the manager UI can surface it.
SLA_HOURS = 24


async def _escalate_overdue_leads() -> int:
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import or_, select

    from app.database import async_session
    from app.models.task import Task

    now = datetime.now(timezone.utc)
    sla_cutoff = now - timedelta(hours=SLA_HOURS)
    escalated = 0
    async with async_session() as session:
        stmt = select(Task).where(
            Task.status == "pending",
            Task.is_urgent.is_(False),
            or_(
                Task.due_at.isnot(None) & (Task.due_at < now),
                Task.due_at.is_(None) & (Task.created_at < sla_cutoff),
            ),
        )
        for task in (await session.execute(stmt)).scalars().all():
            task.is_urgent = True
            task.escalated_at = now
            escalated += 1
        await session.commit()
    logger.info("Overdue leads escalated", tasks=escalated)
    return escalated


@shared_task(name="worker.tasks.maintenance_tasks.escalate_overdue_leads")
def escalate_overdue_leads() -> int:
    return asyncio.run(_escalate_overdue_leads())


# --- Dead source detection (TZ 32) -----------------------------------------
# Sources that stopped producing signals are marked dead so operators can prune
# them and the discovery engine can look for replacements.
DEAD_SOURCE_DAYS = 14


async def _check_dead_sources() -> int:
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import or_, select

    from app.database import async_session
    from app.models.source import Source

    cutoff = datetime.now(timezone.utc) - timedelta(days=DEAD_SOURCE_DAYS)
    dead = 0
    async with async_session() as session:
        stmt = select(Source).where(
            Source.status == "active",
            or_(
                Source.last_checked_at.is_(None) & (Source.created_at < cutoff),
                Source.last_checked_at < cutoff,
            ),
        )
        for source in (await session.execute(stmt)).scalars().all():
            source.status = "dead"
            dead += 1
        await session.commit()
    logger.info("Dead sources flagged", sources=dead)
    return dead


@shared_task(name="worker.tasks.maintenance_tasks.check_dead_sources")
def check_dead_sources() -> int:
    return asyncio.run(_check_dead_sources())
