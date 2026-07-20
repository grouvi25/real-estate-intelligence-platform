"""Analytics router. TZ section 32: overview, funnel, managers, source ROI.

All endpoints require a manager JWT and aggregate only within that manager's
agency. Aggregation is done in SQL (no PII leaves the DB).
"""
from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends
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


def _agency_uuid(current: CurrentManager) -> uuid.UUID:
    return uuid.UUID(current.agency_id)


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

    lead_rows = (
        await session.execute(
            select(func.coalesce(Lead.utm_source, "direct"), func.count())
            .where(Lead.agency_id == aid)
            .group_by(func.coalesce(Lead.utm_source, "direct"))
        )
    ).all()
    leads_by_source = {src: count for src, count in lead_rows}

    deal_rows = (
        await session.execute(
            select(
                func.coalesce(Lead.utm_source, "direct"),
                func.count(DealOutcome.id),
                func.coalesce(func.sum(DealOutcome.commission_amount), 0),
            )
            .select_from(DealOutcome)
            .join(Lead, DealOutcome.lead_id == Lead.id)
            .where(DealOutcome.agency_id == aid, DealOutcome.outcome == WON_OUTCOME)
            .group_by(func.coalesce(Lead.utm_source, "direct"))
        )
    ).all()
    deals_by_source = {src: (deals, int(comm or 0)) for src, deals, comm in deal_rows}

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
