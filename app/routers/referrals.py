"""Partner referrals router. TZ section 20.1.

Transfer a lead to a partner agency: create the referral, mark the lead referred,
create a confirmation task, and notify the partner (best-effort). Manager-scoped.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from app.config import config
from app.database import get_session
from app.dependencies import CurrentManager, get_current_manager
from app.exceptions import AppException, NotFoundError
from app.models.lead import Lead
from app.models.manager import Manager
from app.models.partner_agency import PartnerAgency
from app.models.partner_referral import PartnerReferral
from app.models.task import Task

logger = structlog.get_logger()
router = APIRouter()


class CreateReferralRequest(BaseModel):
    lead_id: uuid.UUID
    partner_agency_id: uuid.UUID
    terms: Optional[str] = None


async def _notify_partner(partner: PartnerAgency, lead: Lead, referral: PartnerReferral) -> None:
    """Best-effort partner notification via the bot layer (never fails the request)."""
    if not partner.contact_telegram:
        return
    try:
        chat_id = int(partner.contact_telegram)
    except (TypeError, ValueError):
        logger.warning("Partner contact_telegram is not numeric; skipping notify", partner_id=str(partner.id))
        return

    from app.services.bot_abstraction import BotButton, BotMessage, BotPlatform, bot_layer

    card = (
        f"Лид #{str(lead.id)[:8]}\n"
        f"Бюджет: {lead.budget_min or 0}–{lead.budget_max or 0}\n"
        f"Сегмент: {lead.segment}"
    )
    await bot_layer.send_message(
        user_id=chat_id,
        platform=BotPlatform.TELEGRAM,
        message=BotMessage(
            text=f"🤝 Новый лид от агентства!\n{card}\nКомиссия: {partner.commission_percent}%",
            buttons=[
                BotButton(text="✅ Принять", url=f"{config.base_url}/referrals/{referral.id}/accept"),
                BotButton(text="❌ Отказать", url=f"{config.base_url}/referrals/{referral.id}/reject"),
            ],
        ),
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_referral(
    req: CreateReferralRequest,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    agency_uuid = uuid.UUID(current.agency_id)

    lead = await session.get(Lead, req.lead_id)
    if lead is None or lead.agency_id != agency_uuid:
        raise NotFoundError("Lead", str(req.lead_id))

    partner = await session.get(PartnerAgency, req.partner_agency_id)
    if partner is None or partner.agency_id != agency_uuid or not partner.is_active:
        raise AppException(status_code=400, detail="Партнёр не найден или неактивен", code="PARTNER_INVALID")

    # Resolve the acting manager (nullable if the token's manager is unknown).
    manager = await session.get(Manager, uuid.UUID(current.manager_id))
    manager_id = manager.id if (manager and manager.agency_id == agency_uuid) else None

    referral = PartnerReferral(
        agency_id=agency_uuid,
        partner_agency_id=partner.id,
        lead_id=lead.id,
        referred_by_manager_id=manager_id,
        geo_location_id=lead.geo_location_id,
        commission_agreed_percent=partner.commission_percent,
        status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(days=config.referral_expiry_days),
        referral_terms=req.terms,
    )
    session.add(referral)

    lead.status = "referred"
    lead.referred_to = partner.id

    session.add(
        Task(
            agency_id=agency_uuid,
            lead_id=lead.id,
            manager_id=manager_id,
            task_type="referral_confirmation",
            title=f"Подтвердить получение лида партнёром {partner.partner_name}",
            due_at=datetime.now(timezone.utc) + timedelta(hours=config.referral_confirmation_hours),
            status="pending",
        )
    )
    await session.flush()
    await session.commit()

    await _notify_partner(partner, lead, referral)

    return {"referral_id": str(referral.id), "status": "sent_to_partner"}
