"""Analytics router. TZ section 32: overview, funnel, managers, source ROI.

All endpoints require a manager JWT and aggregate only within that manager's
agency. Aggregation is done in SQL (no PII leaves the DB).
"""
from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import case, func, select

from app.database import get_session
from app.dependencies import CurrentManager, get_current_manager
from app.models.deal_outcome import DealOutcome
from app.models.lead import Lead
from app.models.manager import Manager
from app.models.property import Property
from app.models.task import Task

logger = structlog.get_logger()
router = APIRouter()

# deal_outcomes.outcome allowed values (migration 001). A "won" deal is
# 'deal_done'; the rest are losses.
WON_OUTCOME = "deal_done"
LOST_OUTCOMES = ("rejected", "lost_to_competitor", "expired")


TIMELINE_MONTHS = 6


def _agency_uuid(current: CurrentManager) -> uuid.UUID:
    return uuid.UUID(current.agency_id)


@router.get("/timeline")
async def analytics_timeline(
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """Won commission per month, oldest first — the last six months.

    Every other endpoint here answers "how much in total", which cannot say
    whether the agency is growing or stalling. Months with no deals are returned
    as zeroes rather than skipped: a gap in a chart has to read as "nothing
    closed", not as "we have no data for that month".
    """
    from datetime import date, datetime, timezone  # noqa: PLC0415

    def month_start(anchor: date, back: int) -> date:
        """`back` months before `anchor`'s month. Plain arithmetic rather than a
        dependency: months are the one calendar unit timedelta cannot express."""
        total = anchor.year * 12 + (anchor.month - 1) - back
        return date(total // 12, total % 12 + 1, 1)

    today = datetime.now(timezone.utc).date()
    first = month_start(today, TIMELINE_MONTHS - 1)

    month = func.date_trunc("month", DealOutcome.deal_closed_at)
    stmt = (
        select(month.label("month"),
               func.coalesce(func.sum(DealOutcome.commission_amount), 0).label("commission"),
               func.count(DealOutcome.id).label("deals"))
        .where(DealOutcome.agency_id == _agency_uuid(current),
               DealOutcome.outcome == WON_OUTCOME,
               DealOutcome.deal_closed_at.isnot(None),
               DealOutcome.deal_closed_at >= first)
        .group_by(month)
    )
    found = {row.month.date().replace(day=1): row for row in (await session.execute(stmt)).all()}

    months = []
    for i in range(TIMELINE_MONTHS):
        start = month_start(today, TIMELINE_MONTHS - 1 - i)
        row = found.get(start)
        months.append({
            "month": start.isoformat(),
            "commission": int(row.commission) if row else 0,
            "deals": int(row.deals) if row else 0,
        })
    return {"months": months}


@router.get("/overview")
async def analytics_overview(
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """Headline totals for the agency dashboard."""
    aid = _agency_uuid(current)

    total_leads = (
        await session.execute(select(func.count()).select_from(Lead).where(Lead.agency_id == aid))
    ).scalar_one()
    active_properties = (
        await session.execute(
            select(func.count()).select_from(Property).where(
                Property.agency_id == aid, Property.status == "active")
        )
    ).scalar_one()
    urgent_tasks = (
        await session.execute(
            select(func.count()).select_from(Task).where(
                Task.agency_id == aid, Task.is_urgent.is_(True), Task.status == "pending")
        )
    ).scalar_one()

    won = (
        await session.execute(
            select(
                func.count().label("deals"),
                func.coalesce(func.sum(DealOutcome.commission_amount), 0).label("commission"),
            ).where(DealOutcome.agency_id == aid, DealOutcome.outcome == WON_OUTCOME)
        )
    ).one()
    lost = (
        await session.execute(
            select(func.count()).select_from(DealOutcome).where(
                DealOutcome.agency_id == aid, DealOutcome.outcome.in_(LOST_OUTCOMES))
        )
    ).scalar_one()

    return {
        "total_leads": total_leads,
        "active_properties": active_properties,
        "urgent_tasks": urgent_tasks,
        "deals_won": won.deals,
        "deals_lost": lost,
        "total_commission": int(won.commission or 0),
        "setup": await _setup_steps(session, aid),
    }


# What has to exist before the agency can actually work, in the order it has to
# exist in. Nothing here was ever explained to a new owner: they signed in, saw
# four zeroes, and had to guess that the catalogue is what makes matching
# possible and that the collector reads only the cities it has been given.
SETUP_STEPS = (
    ("geo", "Укажите города", "Робот ищет только там, где вы работаете", "settings"),
    ("properties", "Загрузите каталог", "Без объектов лиду нечего предложить", "properties/import"),
    ("sources", "Включите источники", "Откуда читать разговоры покупателей", "sources"),
    ("managers", "Позовите менеджеров", "Ссылка-приглашение в профиле", "settings"),
)


async def _setup_steps(session, aid: uuid.UUID) -> dict:
    """Which of the four first-day steps are done. Empty once they all are."""
    from app.models.geo_location import GeoLocation  # noqa: PLC0415
    from app.models.source import Source  # noqa: PLC0415

    from app.services.readiness import SEED_CATALOGUE_MAX  # noqa: PLC0415

    async def _count(model, *where) -> int:
        return int(await session.scalar(
            select(func.count()).select_from(model).where(model.agency_id == aid, *where)) or 0)

    async def _has(model, *where) -> bool:
        return await _count(model, *where) > 0

    done = {
        "geo": await _has(GeoLocation),
        # A handful of rows is what a demo looks like, not a catalogue -- the
        # readiness check has always said so, and the step that asks for one
        # should not tick on the same data readiness calls suspicious.
        "properties": await _count(Property) > SEED_CATALOGUE_MAX,
        "sources": await _has(Source, Source.status.in_(("active", "sandbox"))),
        "managers": (await session.scalar(
            select(func.count()).select_from(Manager).where(Manager.agency_id == aid))) > 1,
    }
    return {
        "done": sum(done.values()),
        "total": len(SETUP_STEPS),
        "steps": [
            {"key": k, "title": t, "hint": h, "route": r, "done": done[k]}
            for k, t, h, r in SETUP_STEPS
        ],
    }


@router.get("/funnel")
async def analytics_funnel(
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """Lead conversion funnel + stage conversion rates."""
    aid = _agency_uuid(current)
    rows = (
        await session.execute(
            select(Lead.status, func.count()).where(Lead.agency_id == aid).group_by(Lead.status)
        )
    ).all()
    by_status = {status: count for status, count in rows}

    total = sum(by_status.values())
    new = by_status.get("new", 0)
    in_progress = by_status.get("in_progress", 0)
    qualified = by_status.get("qualified", 0)
    deal = by_status.get("deal", 0)

    def rate(numerator: int, denominator: int) -> float:
        return round(numerator / denominator * 100, 1) if denominator else 0.0

    return {
        "total": total,
        "stages": {
            "new": new,
            "in_progress": in_progress,
            "qualified": qualified,
            "deal": deal,
        },
        "by_status": by_status,
        "conversion": {
            "new_to_progress": rate(in_progress + qualified + deal, total),
            "progress_to_qualified": rate(qualified + deal, in_progress + qualified + deal),
            "qualified_to_deal": rate(deal, qualified + deal),
            "overall": rate(deal, total),
        },
    }


@router.get("/managers")
async def analytics_managers(
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """Per-manager deal counts and commission."""
    aid = _agency_uuid(current)
    stmt = (
        select(
            Manager.id,
            Manager.name,
            func.count(DealOutcome.id).label("deals"),
            func.coalesce(
                func.sum(case((DealOutcome.outcome == WON_OUTCOME, DealOutcome.commission_amount),
                              else_=0)), 0
            ).label("commission"),
            func.coalesce(
                func.sum(case((DealOutcome.outcome == WON_OUTCOME, 1), else_=0)), 0
            ).label("won"),
        )
        .select_from(Manager)
        .outerjoin(DealOutcome, DealOutcome.manager_id == Manager.id)
        .where(Manager.agency_id == aid)
        .group_by(Manager.id, Manager.name)
        .order_by(func.count(DealOutcome.id).desc())
    )
    rows = (await session.execute(stmt)).all()
    return {
        "managers": [
            {"manager_id": str(mid), "name": name, "deals": deals,
             "deals_won": int(won), "commission": int(commission or 0)}
            for mid, name, deals, commission, won in rows
        ]
    }


@router.get("/source-roi")
async def analytics_source_roi(
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """Attribution: leads generated and commission earned per UTM source."""
    aid = _agency_uuid(current)

    # Group by the raw column (NULLs collapse into one group) and coalesce to
    # "direct" in Python. Grouping by coalesce(...) in SQL would emit two distinct
    # bind params (SELECT vs GROUP BY) that PostgreSQL won't treat as equal.
    lead_rows = (
        await session.execute(
            select(Lead.utm_source, func.count())
            .where(Lead.agency_id == aid)
            .group_by(Lead.utm_source)
        )
    ).all()
    leads_by_source = {(src or "direct"): count for src, count in lead_rows}

    deal_rows = (
        await session.execute(
            select(
                Lead.utm_source,
                func.count(DealOutcome.id),
                func.coalesce(func.sum(DealOutcome.commission_amount), 0),
            )
            .select_from(DealOutcome)
            .join(Lead, DealOutcome.lead_id == Lead.id)
            .where(DealOutcome.agency_id == aid, DealOutcome.outcome == WON_OUTCOME)
            .group_by(Lead.utm_source)
        )
    ).all()
    deals_by_source = {(src or "direct"): (deals, int(comm or 0)) for src, deals, comm in deal_rows}

    sources = []
    for src, lead_count in sorted(leads_by_source.items(), key=lambda kv: kv[1], reverse=True):
        deals, commission = deals_by_source.get(src, (0, 0))
        sources.append({
            "source": src,
            "leads": lead_count,
            "deals_won": deals,
            "commission": commission,
            "conversion_pct": round(deals / lead_count * 100, 1) if lead_count else 0.0,
        })
    return {"sources": sources}


class MarketEventRequest(BaseModel):
    city: str
    event_type: str
    event_data: str


@router.post("/market-event")
async def analyze_market_event(
    req: MarketEventRequest,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """AI-assess a market event's significance for the agency (TZ 27.1)."""
    from app.prompts.market_analysis import SYSTEM_PROMPT_MARKET_EVENT, USER_PROMPT_MARKET
    from app.services.ai_service import AIService, safe_ai_parse

    ai = AIService()
    try:
        res = await ai.complete(
            SYSTEM_PROMPT_MARKET_EVENT,
            USER_PROMPT_MARKET.format(
                city=req.city, event_type=req.event_type, event_data=req.event_data),
            "market_analysis", agency_id=current.agency_id)
    finally:
        await ai.close()
    return {"analysis": safe_ai_parse(res, {"summary": res})}
