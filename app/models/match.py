"""Lead <-> Property match model. Migration 001 table 8."""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UpdatedAtMixin


class LeadPropertyMatch(CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "lead_property_matches"
    __table_args__ = (UniqueConstraint("lead_id", "property_id"),)

    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
    )
    property_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("properties.id", ondelete="CASCADE"), nullable=False
    )
    match_score: Mapped[Optional[int]] = mapped_column(Integer)
    match_reasons: Mapped[list] = mapped_column(JSONB, default=list)
    generated_pitch: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="suggested")
