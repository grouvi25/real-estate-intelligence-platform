"""Lead deduplication. TZ section 32.1 / addendum section 6.

Dedup runs before creating a new lead so the same client arriving from different
channels doesn't create duplicates. Matches by phone (blind index) OR public
telegram_username within a 90-day window, ignoring rejected/archived leads. When
a duplicate is found, the new source is merged into buyer_profile.all_sources.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select

from app.services.encryption import phone_blind_index

WINDOW_DAYS = 90
DEDUP_EXCLUDED_STATUSES = ("rejected", "archived")


async def find_duplicate(
    session,
    agency_id: uuid.UUID,
    phone: Optional[str] = None,
    telegram_username: Optional[str] = None,
    window_days: int = WINDOW_DAYS,
):
    """Return an existing active lead in the agency matching phone or TG username."""
    from app.models.lead import Lead

    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)

    if telegram_username:
        handle = telegram_username.lstrip("@")
        stmt = select(Lead).where(
            Lead.agency_id == agency_id,
            Lead.telegram_username == handle,
            Lead.created_at > cutoff,
            Lead.status.notin_(DEDUP_EXCLUDED_STATUSES),
        ).limit(1)
        found = (await session.execute(stmt)).scalars().first()
        if found is not None:
            return found

    index = phone_blind_index(phone)
    if index:
        stmt = select(Lead).where(
            Lead.agency_id == agency_id,
            Lead.phone_hash == index,
            Lead.created_at > cutoff,
            Lead.status.notin_(DEDUP_EXCLUDED_STATUSES),
        ).limit(1)
        found = (await session.execute(stmt)).scalars().first()
        if found is not None:
            return found

    return None


async def check_and_mark_duplicate(session, lead, source_type: str):
    """Find a duplicate for an unsaved lead; if found, merge the source. TZ 32.1.

    Returns (existing_lead | None, is_duplicate: bool).
    """
    existing = await find_duplicate(
        session, lead.agency_id, phone=lead.phone, telegram_username=lead.telegram_username
    )
    if existing is None:
        return None, False

    profile = dict(existing.buyer_profile or {})
    sources = list(profile.get("all_sources", [existing.source_type or "unknown"]))
    if source_type not in sources:
        sources.append(source_type)
    profile["all_sources"] = sources
    existing.buyer_profile = profile
    await session.commit()
    return existing, True
