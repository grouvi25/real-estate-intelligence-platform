"""Platform operator API: every agency from one place. ТЗ «SaaS-слой» v1, раздел 6.

All endpoints need the operator JWT (get_platform_operator): mint one with
    docker compose exec app python scripts/create_operator_token.py <telegram_id>
The Telegram side of the same work is in the sales bot (app/services/sales_bot.py).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.database import get_session
from app.dependencies import get_platform_operator
from app.exceptions import AppException

router = APIRouter()


def _summary(a) -> dict:
    from app.services.billing import get_subscription_status  # noqa: PLC0415

    return {
        "id": str(a.id), "name": a.name, "city": a.base_city, "plan": a.subscription_plan,
        "status": get_subscription_status(a), "subscription_active": a.subscription_active,
        "expires_at": a.subscription_expires_at.isoformat() if a.subscription_expires_at else None,
        "max_managers": a.max_managers, "max_cities": a.max_cities,
        "owner_telegram_id": a.owner_telegram_id, "bot": a.telegram_bot_username,
        "notes": a.platform_notes, "created_at": a.created_at.isoformat() if a.created_at else None,
    }


async def _agency_or_404(session, agency_id: uuid.UUID):
    from app.models.agency import Agency  # noqa: PLC0415

    agency = await session.get(Agency, agency_id)
    if agency is None:
        raise AppException(404, "Агентство не найдено", "NOT_FOUND")
    return agency


@router.get("/dashboard")
async def dashboard(operator: int = Depends(get_platform_operator), session=Depends(get_session)):
    from app.models.agency import Agency  # noqa: PLC0415
    from app.models.billing import OnboardingRequest  # noqa: PLC0415
    from app.services.billing import SubscriptionStatus, get_subscription_status  # noqa: PLC0415

    agencies = (await session.execute(select(Agency))).scalars().all()
    now = datetime.now(timezone.utc)
    soon = [a for a in agencies if a.subscription_expires_at
            and now < a.subscription_expires_at <= now + timedelta(days=7)]
    statuses = [get_subscription_status(a, now) for a in agencies]
    pending = await session.scalar(select(func.count(OnboardingRequest.id)).where(
        OnboardingRequest.status.in_(("pending", "payment_pending", "paid"))))
    return {
        "total_agencies": len(agencies),
        "active_agencies": statuses.count(SubscriptionStatus.ACTIVE),
        "grace": statuses.count(SubscriptionStatus.GRACE),
        "expired": statuses.count(SubscriptionStatus.EXPIRED),
        "expiring_soon": [_summary(a) for a in soon],
        "open_onboarding_requests": pending or 0,
    }


@router.get("/agencies")
async def agencies(status: Optional[str] = None, operator: int = Depends(get_platform_operator),
                   session=Depends(get_session)):
    from app.models.agency import Agency  # noqa: PLC0415

    rows = [_summary(a) for a in (await session.execute(
        select(Agency).order_by(Agency.created_at.desc()))).scalars().all()]
    return {"agencies": [r for r in rows if status is None or r["status"] == status]}


class ExtendRequest(BaseModel):
    months: int = Field(ge=1, le=36)
    amount_rub: int = Field(default=0, ge=0)
    method: str = "manual"
    note: Optional[str] = None


@router.post("/agencies/{agency_id}/extend")
async def extend(agency_id: uuid.UUID, req: ExtendRequest,
                 operator: int = Depends(get_platform_operator), session=Depends(get_session)):
    from app.services.onboarding import extend_subscription  # noqa: PLC0415

    agency = await extend_subscription(
        session, await _agency_or_404(session, agency_id), req.months, amount_rub=req.amount_rub,
        method=req.method, created_by=f"operator:{operator}", note=req.note)
    return _summary(agency)


class SuspendRequest(BaseModel):
    note: Optional[str] = None


@router.post("/agencies/{agency_id}/suspend")
async def suspend(agency_id: uuid.UUID, req: SuspendRequest = SuspendRequest(),
                  operator: int = Depends(get_platform_operator), session=Depends(get_session)):
    from app.services.billing_admin import set_suspended  # noqa: PLC0415

    return _summary(await set_suspended(session, await _agency_or_404(session, agency_id), True,
                                        f"operator:{operator}", req.note))


@router.post("/agencies/{agency_id}/unsuspend")
async def unsuspend(agency_id: uuid.UUID, operator: int = Depends(get_platform_operator),
                    session=Depends(get_session)):
    from app.services.billing_admin import set_suspended  # noqa: PLC0415

    return _summary(await set_suspended(session, await _agency_or_404(session, agency_id), False,
                                        f"operator:{operator}"))


class AgencyPatch(BaseModel):
    """Plan terms and white-label, as the operator agrees them with the client."""
    subscription_plan: Optional[str] = None
    max_managers: Optional[int] = Field(default=None, ge=1)
    max_cities: Optional[int] = Field(default=None, ge=1)
    monthly_price_rub: Optional[int] = Field(default=None, ge=0)
    brand_color: Optional[str] = None
    logo_url: Optional[str] = None
    welcome_message: Optional[str] = Field(default=None, max_length=1000)
    platform_notes: Optional[str] = None


@router.patch("/agencies/{agency_id}")
async def patch_agency(agency_id: uuid.UUID, req: AgencyPatch,
                       operator: int = Depends(get_platform_operator), session=Depends(get_session)):
    agency = await _agency_or_404(session, agency_id)
    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(agency, field, value)
    await session.commit()
    return _summary(agency)


class BotRequest(BaseModel):
    token: Optional[str] = None  # None or empty -> back to the platform bot


@router.put("/agencies/{agency_id}/bot")
async def set_bot(agency_id: uuid.UUID, req: BotRequest,
                  operator: int = Depends(get_platform_operator), session=Depends(get_session)):
    """ТЗ 4.4: give the agency its own bot (or take it away)."""
    from app.services.agency_bots import AgencyBotError, attach_bot, detach_bot  # noqa: PLC0415

    agency = await _agency_or_404(session, agency_id)
    if not (req.token or "").strip():
        await detach_bot(session, agency)
        return _summary(agency)
    try:
        await attach_bot(session, agency, req.token)
    except AgencyBotError as e:
        raise AppException(400, str(e), "BOT_REJECTED") from None
    return _summary(agency)


@router.get("/onboarding")
async def onboarding(status: str = Query("pending"), operator: int = Depends(get_platform_operator),
                     session=Depends(get_session)):
    from app.models.billing import OnboardingRequest  # noqa: PLC0415

    rows = (await session.execute(select(OnboardingRequest).where(
        OnboardingRequest.status == status).order_by(OnboardingRequest.created_at.desc()))).scalars().all()
    return {"requests": [{
        "id": str(r.id), "short_id": str(r.id)[:8], "status": r.status, "plan": r.plan_id,
        "city": r.city_name, "agency": r.agency_name, "telegram_id": r.telegram_id,
        "username": r.username, "phone": r.phone, "payment_link": r.payment_link,
        "created_at": r.created_at.isoformat(),
    } for r in rows]}


@router.get("/cities")
async def cities(operator: int = Depends(get_platform_operator), session=Depends(get_session)):
    from app.models.agency import Agency  # noqa: PLC0415
    from app.models.geo_location import GeoLocation  # noqa: PLC0415

    rows = (await session.execute(select(GeoLocation, Agency).join(
        Agency, Agency.id == GeoLocation.agency_id))).all()
    return {"cities": [{"city": g.city_name, "region": g.region, "agency": a.name,
                        "agency_id": str(a.id), "agency_active": a.subscription_active}
                       for g, a in rows], "total": len(rows)}


@router.get("/stats")
async def stats(days: int = Query(30, ge=1, le=365), operator: int = Depends(get_platform_operator),
                session=Depends(get_session)):
    from app.models.billing import BillingEvent  # noqa: PLC0415
    from app.models.lead import Lead  # noqa: PLC0415
    from app.models.signal import Signal  # noqa: PLC0415

    since = datetime.now(timezone.utc) - timedelta(days=days)
    return {
        "period_days": days,
        "signals": await session.scalar(select(func.count(Signal.id)).where(Signal.created_at >= since)) or 0,
        "leads": await session.scalar(select(func.count(Lead.id)).where(Lead.created_at >= since)) or 0,
        "revenue_rub": await session.scalar(select(func.sum(BillingEvent.amount_rub)).where(
            BillingEvent.created_at >= since,
            BillingEvent.event_type.in_(("payment", "subscription_renewed")))) or 0,
    }
