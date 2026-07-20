"""Match exclusion model. Migration 005 (TZ section 32 feedback loop).

A hard "never suggest this property to this lead again" record, written when a
manager rejects a suggested match. The matching engine filters these out.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin


class MatchExclusion(CreatedAtMixin, Base):
    __tablename__ = "match_exclusions"
    __table_args__ = (UniqueConstraint("lead_id", "property_id"),)

    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
    )
    property_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("properties.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[Optional[str]] = mapped_column(Text)
    reason: Mapped[Optional[str]] = mapped_column(Text)
