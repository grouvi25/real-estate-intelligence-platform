"""ProtectedGeo model (competitive geo protection). Migration 001 table 3.

Has created_at only (no updated_at) in the schema.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin


class ProtectedGeo(CreatedAtMixin, Base):
    __tablename__ = "protected_geos"
    __table_args__ = (UniqueConstraint("city_name", "region"),)

    city_name: Mapped[str] = mapped_column(Text, nullable=False)
    region: Mapped[Optional[str]] = mapped_column(Text)
    protected_by_agency_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="SET NULL")
    )
    protection_radius_km: Mapped[int] = mapped_column(Integer, default=100)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
