"""Signal model (raw intent signals). Migration 001 table 5."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import TIMESTAMP, ForeignKey, Integer, Text, event, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
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
    #
    # Умолчание обязано быть и на стороне Python. Миграция 055 сделала колонку
    # NOT NULL DEFAULT 'reip_scouting', но умолчание базы срабатывает только
    # когда колонки нет в INSERT — а SQLAlchemy подставляла явный NULL, потому
    # что поле описано и пусто. Так падали четырнадцать тестов в CI.
    origin_system: Mapped[str] = mapped_column(
        Text, default="reip_scouting", server_default=text("'reip_scouting'")
    )
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
    # ТЗ «Сигналы» v1.0, апгрейд B (migration 066): purchase | rental | news |
    # competitor | other. Collectors set it with the agency's competitor names;
    # anything else that inserts a signal gets the keyword category below.
    signal_category: Mapped[Optional[str]] = mapped_column(Text, default=None)

    # One-directional convenience relationships (used by scoring/pipeline code).
    geo_location: Mapped[Optional[GeoLocation]] = relationship("GeoLocation", lazy="joined")
    source: Mapped[Optional[Source]] = relationship("Source", lazy="joined")


class AgencySignalFilter(Base):
    """Which categories the signal list opens with (ТЗ «Сигналы» 6.1)."""
    __tablename__ = "agency_signal_filters"

    id = None  # the agency is the key; Base's UUID id does not exist here
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), primary_key=True)
    enabled_cats: Mapped[list] = mapped_column(ARRAY(Text), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()"), onupdate=text("now()"))


@event.listens_for(Signal, "before_insert")
def _default_category(mapper, connection, target) -> None:
    if not target.signal_category:
        from app.services.signal_classifier import classify_category  # noqa: PLC0415

        target.signal_category = classify_category(target.raw_text)
