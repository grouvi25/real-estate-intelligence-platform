"""GeoLocation model (sales cities / multi-geo). Migration 001 table 2."""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UpdatedAtMixin


class GeoLocation(CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "geo_locations"

    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False
    )
    city_name: Mapped[str] = mapped_column(Text, nullable=False)
    region: Mapped[Optional[str]] = mapped_column(Text)
    geo_type: Mapped[str] = mapped_column(Text, nullable=False)  # base | sales | partner
    market_profile: Mapped[dict] = mapped_column(JSONB, default=dict)
    keywords: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_discovery_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    partner_agency_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
