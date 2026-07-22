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
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.config import config
from app.database import get_session
from app.dependencies import CurrentManager, get_current_manager
from app.exceptions import AppException, NotFoundError
from app.models.deal_outcome import DealOutcome
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


class RecordReferralDealRequest(BaseModel):
    deal_amount: Optional[int] = None
    commission_amount: int = 0


TRUST_PROMOTION = [(15, "premium"), (5, "verified")]  # deals_count threshold -> level


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
                BotButton(text="✅ Принять", url=f"{config.base_url}/api/referrals/{referral.id}/accept"),
                BotButton(text="❌ Отказать", url=f"{config.base_url}/api/referrals/{referral.id}/reject"),
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


@router.get("")
async def list_referrals(
    status_filter: Optional[str] = None,
    partner_agency_id: Optional[uuid.UUID] = None,
    limit: int = 100,
    offset: int = 0,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """List referrals for the current agency (newest first), with lead + partner."""
    limit = min(max(limit, 1), 200)
    offset = max(offset, 0)
    stmt = (
        select(PartnerReferral, Lead, PartnerAgency)
        .join(Lead, PartnerReferral.lead_id == Lead.id)
        .join(PartnerAgency, PartnerReferral.partner_agency_id == PartnerAgency.id)
        .where(PartnerReferral.agency_id == uuid.UUID(current.agency_id))
    )
    if status_filter:
        stmt = stmt.where(PartnerReferral.status == status_filter)
    if partner_agency_id:
        stmt = stmt.where(PartnerReferral.partner_agency_id == partner_agency_id)
    stmt = stmt.order_by(PartnerReferral.created_at.desc()).limit(limit).offset(offset)

    rows = (await session.execute(stmt)).all()
    return {
        "count": len(rows),
        "referrals": [
            {
                "id": str(ref.id),
                "lead_id": str(ref.lead_id),
                "lead_name": lead.name,
                "partner_agency_id": str(partner.id),
                "partner_name": partner.partner_name,
                "status": ref.status,
                "commission_agreed_percent": ref.commission_agreed_percent,
                "deal_amount": ref.deal_amount,
                "commission_amount": ref.commission_amount,
                "expires_at": ref.expires_at.isoformat() if ref.expires_at else None,
                "created_at": ref.created_at.isoformat() if ref.created_at else None,
            }
            for ref, lead, partner in rows
        ],
    }


@router.post("/{referral_id}/deal", status_code=status.HTTP_201_CREATED)
async def record_referral_deal(
    referral_id: uuid.UUID,
    req: RecordReferralDealRequest,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """Close a referral as a completed deal: record the commission our agency
    earned, bump the partner's stats + trust level, and log a referral_deal
    outcome for the Knowledge Moat."""
    agency_uuid = uuid.UUID(current.agency_id)
    referral = await session.get(PartnerReferral, referral_id)
    if referral is None or referral.agency_id != agency_uuid:
        raise NotFoundError("Referral", str(referral_id))
    if referral.status == "deal":
        raise AppException(status_code=409, detail="Реферал уже закрыт сделкой", code="ALREADY_DEAL")

    now = datetime.now(timezone.utc)
    referral.status = "deal"
    referral.deal_amount = req.deal_amount
    referral.commission_amount = req.commission_amount
    referral.deal_closed_at = now
    referral.status_updated_at = now

    partner = await session.get(PartnerAgency, referral.partner_agency_id)
    if partner is not None:
        partner.deals_count = (partner.deals_count or 0) + 1
        partner.total_commission_earned = (partner.total_commission_earned or 0) + (req.commission_amount or 0)
        for threshold, level in TRUST_PROMOTION:
            if partner.deals_count >= threshold:
                partner.trust_level = level
                break

    lead = await session.get(Lead, referral.lead_id)
    session.add(
        DealOutcome(
            agency_id=agency_uuid,
            lead_id=referral.lead_id,
            manager_id=referral.referred_by_manager_id,
            geo_location_id=referral.geo_location_id,
            outcome="referral_deal",
            deal_amount=req.deal_amount,
            commission_amount=req.commission_amount,
            deal_closed_at=now,
            buyer_segment=lead.segment if lead else None,
        )
    )
    await session.commit()

    logger.info("Referral deal recorded", referral_id=str(referral_id),
                commission=req.commission_amount)
    return {
        "referral_id": str(referral_id),
        "status": referral.status,
        "partner_deals_count": partner.deals_count if partner else None,
        "partner_trust_level": partner.trust_level if partner else None,
    }


def _referral_page(title: str, message: str) -> HTMLResponse:
    """Minimal confirmation page shown to a partner who clicked accept/reject."""
    html = (
        "<!doctype html><html lang=\"ru\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{title}</title>"
        "<style>body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#0f1115;"
        "color:#e8eaed;display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0}"
        ".card{max-width:420px;padding:32px;text-align:center}"
        "h1{font-size:20px;margin:0 0 12px}p{color:#9aa0a6;line-height:1.5}</style></head>"
        f"<body><div class=\"card\"><h1>{title}</h1><p>{message}</p></div></body></html>"
    )
    return HTMLResponse(content=html)


async def _transition_referral(referral_id: uuid.UUID, new_status: str, session) -> tuple[str, str]:
    """Move a pending referral to accepted/rejected. Returns (title, message).

    Public link (the partner has no JWT); the unguessable referral UUID is the
    capability. Idempotent: a second click just reports the current status.
    """
    referral = await session.get(PartnerReferral, referral_id)
    if referral is None:
        return ("Реферал не найден", "Ссылка недействительна или реферал удалён.")

    now = datetime.now(timezone.utc)
    if referral.status != "pending":
        labels = {"accepted": "уже принят", "rejected": "уже отклонён",
                  "expired": "истёк", "deal": "завершён сделкой"}
        return ("Реферал обработан", f"Этот реферал {labels.get(referral.status, referral.status)}.")

    referral.status = new_status
    referral.status_updated_at = now
    if new_status == "accepted":
        referral.accepted_at = now
    await session.commit()

    # Notify the agency manager who sent the referral (best-effort).
    if referral.referred_by_manager_id:
        from app.services.bot_abstraction import bot_layer

        verb = "принял" if new_status == "accepted" else "отклонил"
        try:
            await bot_layer.notify_manager(
                str(referral.referred_by_manager_id),
                f"{'✅' if new_status == 'accepted' else '❌'} Партнёр {verb} лид "
                f"#{str(referral.lead_id)[:8]}.",
            )
        except Exception:  # noqa: BLE001
            pass

    if new_status == "accepted":
        return ("Реферал принят", "Спасибо! Агентство уведомлено, что вы приняли лид в работу.")
    return ("Реферал отклонён", "Готово. Агентство уведомлено об отказе.")


@router.get("/{referral_id}/accept", response_class=HTMLResponse)
async def accept_referral(referral_id: uuid.UUID, session=Depends(get_session)):
    title, message = await _transition_referral(referral_id, "accepted", session)
    return _referral_page(title, message)


@router.get("/{referral_id}/reject", response_class=HTMLResponse)
async def reject_referral(referral_id: uuid.UUID, session=Depends(get_session)):
    title, message = await _transition_referral(referral_id, "rejected", session)
    return _referral_page(title, message)
