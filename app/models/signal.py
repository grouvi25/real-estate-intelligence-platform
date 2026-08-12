"""Signal model (raw intent signals). Migration 001 table 5."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import TIMESTAMP, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, UpdatedAtMixin
from app.models.geo_location import GeoLocation
from app.models.source import Source


class Signal(CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "signals"

    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id", ondelete="SET NULL")
    )
    geo_location_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("geo_locations.id", ondelete="SET NULL")
    )
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    # Migration 045: repost dedup, see intent_scoring.content_fingerprint.
    content_fingerprint: Mapped[Optional[str]] = mapped_column(Text)
    author_hash: Mapped[Optional[str]] = mapped_column(Text)
    author_display_name: Mapped[Optional[str]] = mapped_column(Text)
    signal_url: Mapped[Optional[str]] = mapped_column(Text)
    intent_score: Mapped[Optional[int]] = mapped_column(Integer)
    segment: Mapped[Optional[str]] = mapped_column(Text)
    budget_min: Mapped[Optional[int]] = mapped_column(Integer)
    budget_max: Mapped[Optional[int]] = mapped_column(Integer)
    location_interest: Mapped[Optional[str]] = mapped_column(Text)
    urgency: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="new")
    ai_analysis: Mapped[dict] = mapped_column(JSONB, default=dict)

    # Signal Bus addendum (migrations 040-041).
    origin_system: Mapped[Optional[str]] = mapped_column(Text)
    content_unit_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_units.id", ondelete="SET NULL")
    )
    reply_channel: Mapped[Optional[str]] = mapped_column(Text)
    reply_status: Mapped[str] = mapped_column(Text, default="pending")
    reply_draft: Mapped[Optional[str]] = mapped_column(Text)
    replied_by_manager_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("managers.id", ondelete="SET NULL")
    )
    replied_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    # Why a signal left the queue without an answer, and on whose call
    # (addendum §5.2: escalated / dismissed). Migration 052.
    triage_reason: Mapped[Optional[str]] = mapped_column(Text)
    triaged_by_manager_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("managers.id", ondelete="SET NULL")
    )
    triaged_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))

    # One-directional convenience relationships (used by scoring/pipeline code).
    geo_location: Mapped[Optional[GeoLocation]] = relationship("GeoLocation", lazy="joined")
    source: Mapped[Optional[Source]] = relationship("Source", lazy="joined")
