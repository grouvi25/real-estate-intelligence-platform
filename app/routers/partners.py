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
from sqlalchemy import select

from app.database import get_session
from app.dependencies import CurrentManager, get_current_manager
from app.exceptions import NotFoundError, ValidationError
from app.models.partner_agency import PartnerAgency

logger = structlog.get_logger()
router = APIRouter()

COMMISSION_TYPES = {"percent", "fixed", "hybrid"}


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


class UpdatePartnerRequest(BaseModel):
    is_active: Optional[bool] = None
    commission_percent: Optional[float] = None


def _partner_dto(p: PartnerAgency) -> dict:
    return {
        "id": str(p.id),
        "partner_name": p.partner_name,
        "partner_city": p.partner_city,
        "partner_region": p.partner_region,
        "contact_name": p.contact_name,
        "contact_telegram": p.contact_telegram,
        "commission_percent": p.commission_percent,
        "commission_type": p.commission_type,
        "trust_level": p.trust_level,
        "deals_count": p.deals_count,
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
    if req.is_active is not None:
        partner.is_active = req.is_active
    if req.commission_percent is not None:
        partner.commission_percent = req.commission_percent
    await session.commit()
    return _partner_dto(partner)
