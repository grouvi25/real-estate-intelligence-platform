"""Source discovery log. Migration 001 table 14.

Has neither created_at nor updated_at - only processed_at.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import TIMESTAMP, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SourceDiscoveryLog(Base):
    __tablename__ = "source_discovery_log"

    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False
    )
    geo_location_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("geo_locations.id", ondelete="SET NULL")
    )
    discovery_method: Mapped[Optional[str]] = mapped_column(Text)
    found_sources: Mapped[list] = mapped_column(JSONB, default=list)
    processed_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
