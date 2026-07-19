"""Property model (real estate objects). Migration 001 table 7."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Optional

from sqlalchemy import Boolean, Date, Float, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UpdatedAtMixin


class Property(CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "properties"

    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False
    )
    geo_location_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("geo_locations.id", ondelete="SET NULL")
    )
    partner_agency_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    property_type: Mapped[Optional[str]] = mapped_column(Text)
    deal_type: Mapped[str] = mapped_column(Text, default="sale")
    developer: Mapped[Optional[str]] = mapped_column(Text)
    address: Mapped[Optional[str]] = mapped_column(Text)
    district: Mapped[Optional[str]] = mapped_column(Text)
    price: Mapped[Optional[int]] = mapped_column(Integer)
    price_per_sqm: Mapped[Optional[int]] = mapped_column(Integer)
    area_total: Mapped[Optional[float]] = mapped_column(Float)
    area_living: Mapped[Optional[float]] = mapped_column(Float)
    rooms: Mapped[Optional[int]] = mapped_column(Integer)
    floor: Mapped[Optional[int]] = mapped_column(Integer)
    floors_total: Mapped[Optional[int]] = mapped_column(Integer)
    year_built: Mapped[Optional[int]] = mapped_column(Integer)
    is_new_build: Mapped[bool] = mapped_column(Boolean, default=False)
    readiness_status: Mapped[Optional[str]] = mapped_column(Text)
    readiness_date: Mapped[Optional[date]] = mapped_column(Date)
    amenities: Mapped[list] = mapped_column(JSONB, default=list)
    target_segments: Mapped[list] = mapped_column(JSONB, default=list)
    investment_roi: Mapped[Optional[float]] = mapped_column(Float)
    description_original: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="active")
    source_url: Mapped[Optional[str]] = mapped_column(Text)
    images: Mapped[list] = mapped_column(JSONB, default=list)
    ai_analysis: Mapped[dict] = mapped_column(JSONB, default=dict)
