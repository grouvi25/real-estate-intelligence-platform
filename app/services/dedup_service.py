"""Lead deduplication by phone (blind index). TZ addendum section 6 / TZ 32.

Dedup happens before creating a new lead / exporting to CRM, so the same client
arriving from different channels doesn't create duplicate leads.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select

from app.services.encryption import phone_blind_index


async def find_duplicate(session, agency_id: uuid.UUID, phone: Optional[str]):
    """Return an existing lead in the agency with the same phone, or None."""
    from app.models.lead import Lead

    index = phone_blind_index(phone)
    if not index:
        return None
    stmt = select(Lead).where(Lead.agency_id == agency_id, Lead.phone_hash == index)
    return (await session.execute(stmt)).scalars().first()
