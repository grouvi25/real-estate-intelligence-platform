"""Source model (monitoring sources). Migration 001 table 4.

Note: the DB column ``metadata`` is mapped to the attribute ``meta`` because
``metadata`` is reserved on SQLAlchemy declarative classes.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import TIMESTAMP, Boolean, Float, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UpdatedAtMixin


class Source(CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "sources"

    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False
    )
    geo_location_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("geo_locations.id", ondelete="SET NULL")
    )
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_name: Mapped[Optional[str]] = mapped_column(Text)
    external_id: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="sandbox")
    score: Mapped[int] = mapped_column(Integer, default=0)
    signals_per_day: Mapped[float] = mapped_column(Float, default=0)
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    auto_found: Mapped[bool] = mapped_column(Boolean, default=False)
    meta: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
