"""Deal outcome model (Knowledge Moat). Migration 001 table 13.

Has created_at only (no updated_at) in the schema.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import TIMESTAMP, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin


class DealOutcome(CreatedAtMixin, Base):
    __tablename__ = "deal_outcomes"

    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False
    )
    lead_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="SET NULL")
    )
    property_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("properties.id", ondelete="SET NULL")
    )
    source_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id", ondelete="SET NULL")
    )
    manager_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("managers.id", ondelete="SET NULL")
    )
    geo_location_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("geo_locations.id", ondelete="SET NULL")
    )
    partner_referral_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("partner_referrals.id", ondelete="SET NULL")
    )
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    deal_amount: Mapped[Optional[int]] = mapped_column(Integer)
    commission_amount: Mapped[Optional[int]] = mapped_column(Integer)
    deal_closed_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    source_to_signal_days: Mapped[Optional[int]] = mapped_column(Integer)
    signal_to_lead_days: Mapped[Optional[int]] = mapped_column(Integer)
    lead_to_contact_days: Mapped[Optional[int]] = mapped_column(Integer)
    contact_to_deal_days: Mapped[Optional[int]] = mapped_column(Integer)
    total_days_to_close: Mapped[Optional[int]] = mapped_column(Integer)
    winning_factors: Mapped[list] = mapped_column(JSONB, default=list)
    losing_factors: Mapped[list] = mapped_column(JSONB, default=list)
    objections_overcome: Mapped[list] = mapped_column(JSONB, default=list)
    buyer_segment: Mapped[Optional[str]] = mapped_column(Text)
    lead_magnet_used: Mapped[Optional[str]] = mapped_column(Text)
