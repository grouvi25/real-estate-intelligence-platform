"""Partner referral model (handoff of leads to partners). Migration 001 table 12.

Has created_at only (no updated_at) in the schema.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import TIMESTAMP, Boolean, Float, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin


class PartnerReferral(CreatedAtMixin, Base):
    __tablename__ = "partner_referrals"

    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False
    )
    partner_agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("partner_agencies.id", ondelete="CASCADE"), nullable=False
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
    )
    referred_by_manager_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("managers.id", ondelete="SET NULL")
    )
    geo_location_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("geo_locations.id", ondelete="SET NULL")
    )
    referral_terms: Mapped[Optional[str]] = mapped_column(Text)
    commission_agreed_percent: Mapped[Optional[float]] = mapped_column(Float)
    commission_agreed_fixed: Mapped[Optional[int]] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, default="pending")
    deal_amount: Mapped[Optional[int]] = mapped_column(Integer)
    commission_amount: Mapped[Optional[int]] = mapped_column(Integer)
    partner_feedback: Mapped[Optional[str]] = mapped_column(Text)
    partner_contact_added: Mapped[bool] = mapped_column(Boolean, default=False)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    deal_closed_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    expires_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    status_updated_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
