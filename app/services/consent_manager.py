"""152-ФЗ: consent, export and erasure of a subject's personal data.

The manifest (TZ section 3) names this file and the law behind it. Consent was
being recorded properly — text, version, timestamp, IP — but only the half of
the law that lets us collect. The other half, the subject's own rights, had no
implementation at all: §14 gives them the right to receive their data and §21
obliges the operator to erase it on request within seven working days. Doing
that with hand-written SQL is not a process a court would accept, and there was
nothing else on offer.

Two operations, both leaving a trace in activity_log because "we did erase it"
has to be provable afterwards:

    export_lead_data  — everything held about one person, decrypted, as JSON
    erase_lead_data   — the personal data destroyed, the business record kept

Erasure keeps the row. Deleting the lead outright would take its signals, tasks
and deal outcome with it, and those carry no personal data once the identifiers
are gone — but they are what the agency's own accounting stands on. So the
identifiers are destroyed, the row is marked erased, and everything anonymous
stays: how the deal went, what it earned, which source it came from.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

logger = structlog.get_logger()

ERASED_MARK = "[удалено по 152-ФЗ]"


async def _log(session, lead, action: str, manager_id: Optional[str], details: dict) -> None:
    from app.models.activity_log import ActivityLog  # noqa: PLC0415

    session.add(ActivityLog(
        agency_id=lead.agency_id,
        lead_id=lead.id,
        manager_id=uuid.UUID(manager_id) if manager_id else None,
        action_type=action,
        description=details.pop("description", None),
        meta=details,
    ))


async def export_lead_data(session, lead: Any) -> dict:
    """Everything the platform holds about this person, in readable form.

    §14: the subject may ask what is stored about them. Encrypted fields are
    returned decrypted — it is their own data, and a ciphertext answers nothing.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.activity_log import ActivityLog  # noqa: PLC0415
    from app.models.signal import Signal  # noqa: PLC0415
    from app.models.task import Task  # noqa: PLC0415

    signals = (await session.execute(
        select(Signal).where(Signal.id == lead.source_signal_id)
    )).scalars().all() if lead.source_signal_id else []

    tasks = (await session.execute(
        select(Task).where(Task.lead_id == lead.id)
    )).scalars().all()

    history = (await session.execute(
        select(ActivityLog).where(ActivityLog.lead_id == lead.id)
        .order_by(ActivityLog.created_at)
    )).scalars().all()

    data = {
        "lead": {
            "id": str(lead.id),
            "name": lead.name,
            "phone": lead.phone,
            "email": lead.email,
            "telegram_username": lead.telegram_username,
            "segment": lead.segment,
            "purchase_goal": lead.purchase_goal,
            "budget_min": lead.budget_min,
            "budget_max": lead.budget_max,
            "status": lead.status,
            "buyer_profile": lead.buyer_profile,
            "created_at": lead.created_at.isoformat() if lead.created_at else None,
        },
        "consent": {
            "given": lead.consent_given,
            "given_at": lead.consent_given_at.isoformat() if lead.consent_given_at else None,
            "text": lead.consent_text,
            "version": lead.consent_version,
            "ip": str(lead.consent_ip) if lead.consent_ip else None,
            "user_agent": lead.consent_user_agent,
        },
        "source_signals": [
            {"id": str(s.id), "text": s.raw_text, "url": s.signal_url,
             "collected_at": s.created_at.isoformat() if s.created_at else None}
            for s in signals
        ],
        "tasks": [
            {"id": str(t.id), "title": t.title, "status": t.status,
             "created_at": t.created_at.isoformat() if t.created_at else None}
            for t in tasks
        ],
        "history": [
            {"action": h.action_type, "description": h.description, "details": h.meta,
             "at": h.created_at.isoformat() if h.created_at else None}
            for h in history
        ],
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }

    await _log(session, lead, "pd_export", None, {"fields": len(data["lead"])})
    await session.commit()
    logger.info("PD exported", lead_id=str(lead.id))
    return data


async def erase_lead_data(session, lead: Any, manager_id: Optional[str] = None,
                          reason: str = "Запрос субъекта ПД") -> dict:
    """Destroy the identifiers, keep the anonymous business record.

    §21: on withdrawal of consent the operator stops processing and erases the
    personal data. What is left after that — that a deal closed, for how much,
    from which source — identifies nobody and is the agency's own accounting.
    """
    from sqlalchemy import update  # noqa: PLC0415

    from app.models.signal import Signal  # noqa: PLC0415

    erased_signals = 0
    if lead.source_signal_id:
        # The raw message is the person's own words and often carries a name or
        # a phone number in the text itself.
        result = await session.execute(
            update(Signal)
            .where(Signal.id == lead.source_signal_id)
            .values(raw_text=ERASED_MARK, author_display_name=None, reply_draft=None)
        )
        erased_signals = result.rowcount or 0

    lead.name = None
    lead.phone = None
    lead.email = None
    lead.telegram_username = None
    lead.phone_hash = None          # the blind index is derived from the number
    lead.buyer_profile = {}         # free text about the person
    lead.consent_given = False
    lead.consent_text = f"{ERASED_MARK}: {reason}"
    lead.pd_erased_at = datetime.now(timezone.utc)
    lead.status = "archived"

    await _log(session, lead, "pd_erased", manager_id,
               {"reason": reason, "signals_cleared": erased_signals})
    await session.commit()

    # Deliberately not logging what was erased.
    logger.info("PD erased", lead_id=str(lead.id), signals_cleared=erased_signals)
    return {
        "erased": True,
        "lead_id": str(lead.id),
        "signals_cleared": erased_signals,
        "kept": "обезличенная статистика сделки",
    }


async def find_leads_by_phone(session, agency_id, phone: str) -> list:
    """Locate a subject by the number they call from, without decrypting the base.

    Requests arrive as "удалите мои данные, мой номер такой-то"; the blind index
    is exactly what it is for.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.lead import Lead  # noqa: PLC0415
    from app.services.encryption import phone_blind_index  # noqa: PLC0415

    digest = phone_blind_index(phone)
    if not digest:
        return []
    return (await session.execute(
        select(Lead).where(Lead.agency_id == agency_id, Lead.phone_hash == digest)
    )).scalars().all()
