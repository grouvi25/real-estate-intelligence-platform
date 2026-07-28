"""Partner agencies router. TZ section 20 (partner network).

Manager-scoped CRUD-lite for partner agencies: list active partners (used by the
referral flow to pick a recipient) and register a new partner. Contact phone is
PII and stored encrypted.
"""
from __future__ import annotations

import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import func, select

from app.database import get_session
from app.dependencies import CurrentManager, get_current_manager
from app.exceptions import NotFoundError, ValidationError
from app.models.lead import Lead
from app.models.partner_agency import PartnerAgency
from app.models.partner_referral import PartnerReferral

logger = structlog.get_logger()
router = APIRouter()

COMMISSION_TYPES = {"percent", "fixed", "hybrid"}
TRUST_LEVELS = {"standard", "verified", "premium"}


class CreatePartnerRequest(BaseModel):
    partner_name: str
    partner_city: str
    partner_region: Optional[str] = None
    contact_name: Optional[str] = None
    contact_telegram: Optional[str] = None
    contact_phone: Optional[str] = None
    commission_percent: Optional[float] = None
    commission_type: str = "percent"
    notes: Optional[str] = None


class AcceptPartnerGeoRequest(BaseModel):
    """Accept the referral offer returned by POST /api/geo for a covered city."""

    partner_id: uuid.UUID
    city_name: str
    region: Optional[str] = None
    market_type: str = "urban"


class UpdatePartnerRequest(BaseModel):
    partner_name: Optional[str] = None
    partner_city: Optional[str] = None
    partner_region: Optional[str] = None
    contact_name: Optional[str] = None
    contact_telegram: Optional[str] = None
    contact_phone: Optional[str] = None
    commission_percent: Optional[float] = None
    commission_fixed: Optional[int] = None
    commission_type: Optional[str] = None
    trust_level: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


def _partner_dto(p: PartnerAgency) -> dict:
    return {
        "id": str(p.id),
        "partner_name": p.partner_name,
        "partner_city": p.partner_city,
        "partner_region": p.partner_region,
        "contact_name": p.contact_name,
        "contact_telegram": p.contact_telegram,
        "contact_phone": p.contact_phone,
        "commission_percent": p.commission_percent,
        "commission_fixed": p.commission_fixed,
        "commission_type": p.commission_type,
        "trust_level": p.trust_level,
        "deals_count": p.deals_count,
        "total_commission_earned": p.total_commission_earned,
        "notes": p.notes,
        "is_active": p.is_active,
    }


@router.get("")
async def list_partners(
    active_only: bool = True,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    stmt = select(PartnerAgency).where(PartnerAgency.agency_id == uuid.UUID(current.agency_id))
    if active_only:
        stmt = stmt.where(PartnerAgency.is_active.is_(True))
    stmt = stmt.order_by(PartnerAgency.partner_name)
    rows = (await session.execute(stmt)).scalars().all()
    return {"count": len(rows), "partners": [_partner_dto(p) for p in rows]}


@router.post("/accept", status_code=status.HTTP_201_CREATED)
async def accept_partner_geo(
    req: AcceptPartnerGeoRequest,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """Open a partner-served city in referral mode. TZ 28.1.

    Adding a city another agency's partner covers returns 202 partner_offer with
    `"action": "POST /api/partners/accept"` (app/routers/geo.py) -- and that
    endpoint did not exist, so the offer was a dead end and the city could never
    be opened at all.

    Accepting creates the geo with geo_type='partner' and the partner attached,
    so discovery and signal collection run for the agency while deals are handed
    over through the referral flow.
    """
    from app.models.geo_location import GeoLocation

    agency_id = uuid.UUID(current.agency_id)
    partner = await session.get(PartnerAgency, req.partner_id)
    if partner is None or str(partner.agency_id) != current.agency_id:
        raise NotFoundError("Partner", str(req.partner_id))
    if not partner.is_active:
        raise ValidationError("partner_id", "партнёр отключён")

    existing = await session.scalar(
        select(GeoLocation.id).where(
            GeoLocation.agency_id == agency_id,
            GeoLocation.city_name == req.city_name,
            GeoLocation.region == req.region,
        )
    )
    if existing:
        raise ValidationError("city_name", "город уже добавлен")

    geo = GeoLocation(
        agency_id=agency_id,
        city_name=req.city_name,
        region=req.region,
        geo_type="partner",
        partner_agency_id=partner.id,
        market_profile={"type": req.market_type, "via_partner": partner.partner_name},
        auto_discovery_enabled=True,
    )
    session.add(geo)
    await session.commit()

    # Same follow-up as a normal geo: without keywords quick_filter has no city
    # to match on and the city yields nothing.
    from worker.tasks.geo_tasks import generate_keywords_for_geo

    generate_keywords_for_geo.delay(
        str(geo.id),
        {"city_name": req.city_name, "region": req.region, "market_type": req.market_type,
         "agency_id": str(agency_id)},
    )

    logger.info("Partner geo accepted", geo_id=str(geo.id), partner_id=str(partner.id))
    return {
        "geo_id": str(geo.id),
        "status": "partner_mode",
        "partner_id": str(partner.id),
        "partner_name": partner.partner_name,
        "message": (
            f"Город {req.city_name} открыт через партнёра {partner.partner_name}. "
            "Сделки передаются партнёру через рефералы."
        ),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_partner(
    req: CreatePartnerRequest,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    if req.commission_type not in COMMISSION_TYPES:
        raise ValidationError("commission_type", f"недопустимый тип: {req.commission_type}")

    partner = PartnerAgency(
        agency_id=uuid.UUID(current.agency_id),
        partner_name=req.partner_name,
        partner_city=req.partner_city,
        partner_region=req.partner_region,
        contact_name=req.contact_name,
        contact_telegram=req.contact_telegram,
        commission_percent=req.commission_percent,
        commission_type=req.commission_type,
        notes=req.notes,
        is_active=True,
    )
    partner.contact_phone = req.contact_phone
    session.add(partner)
    await session.commit()
    logger.info("Partner created", partner_id=str(partner.id), agency_id=current.agency_id)
    return _partner_dto(partner)


@router.get("/{partner_id}")
async def get_partner(
    partner_id: uuid.UUID,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """Partner detail + aggregate stats + referral history (agency-scoped)."""
    partner = await session.get(PartnerAgency, partner_id)
    if partner is None or str(partner.agency_id) != current.agency_id:
        raise NotFoundError("Partner", str(partner_id))

    stmt = (
        select(PartnerReferral, Lead)
        .join(Lead, PartnerReferral.lead_id == Lead.id)
        .where(PartnerReferral.partner_agency_id == partner_id)
        .order_by(PartnerReferral.created_at.desc())
    )
    rows = (await session.execute(stmt)).all()
    referrals = []
    stats = {"total": 0, "pending": 0, "accepted": 0, "in_progress": 0,
             "deal_done": 0, "rejected": 0, "expired": 0, "dispute": 0}
    for ref, lead in rows:
        stats["total"] += 1
        stats[ref.status] = stats.get(ref.status, 0) + 1
        referrals.append({
            "id": str(ref.id),
            "lead_id": str(ref.lead_id),
            "lead_name": lead.name,
            "status": ref.status,
            "commission_agreed_percent": ref.commission_agreed_percent,
            "deal_amount": ref.deal_amount,
            "commission_amount": ref.commission_amount,
            "created_at": ref.created_at.isoformat() if ref.created_at else None,
        })

    dto = _partner_dto(partner)
    dto["stats"] = stats
    dto["referrals"] = referrals
    return dto


@router.patch("/{partner_id}")
async def update_partner(
    partner_id: uuid.UUID,
    req: UpdatePartnerRequest,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    partner = await session.get(PartnerAgency, partner_id)
    if partner is None or str(partner.agency_id) != current.agency_id:
        raise NotFoundError("Partner", str(partner_id))

    if req.commission_type is not None and req.commission_type not in COMMISSION_TYPES:
        raise ValidationError("commission_type", f"недопустимый тип: {req.commission_type}")
    if req.trust_level is not None and req.trust_level not in TRUST_LEVELS:
        raise ValidationError("trust_level", f"недопустимый уровень: {req.trust_level}")

    fields = req.model_dump(exclude_unset=True)
    # contact_phone is a hybrid setter (encrypts); handle separately.
    if "contact_phone" in fields:
        partner.contact_phone = fields.pop("contact_phone")
    for key, value in fields.items():
        setattr(partner, key, value)
    await session.commit()
    return _partner_dto(partner)


@router.delete("/{partner_id}")
async def delete_partner(
    partner_id: uuid.UUID,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """Delete a partner that has no referral history (else deactivate instead)."""
    from app.exceptions import AppException

    partner = await session.get(PartnerAgency, partner_id)
    if partner is None or str(partner.agency_id) != current.agency_id:
        raise NotFoundError("Partner", str(partner_id))

    count = (
        await session.execute(
            select(func.count()).select_from(PartnerReferral).where(
                PartnerReferral.partner_agency_id == partner_id)
        )
    ).scalar_one()
    if count:
        raise AppException(
            status_code=409,
            detail="У партнёра есть рефералы — отключите его вместо удаления",
            code="PARTNER_HAS_REFERRALS",
        )
    await session.delete(partner)
    await session.commit()
    return {"status": "deleted", "id": str(partner_id)}
