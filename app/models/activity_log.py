"""Activity log (audit). Migration 001 table 15.

Has created_at only. DB column ``metadata`` mapped to attribute ``meta``.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin


class ActivityLog(CreatedAtMixin, Base):
    __tablename__ = "activity_log"

    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False
    )
    lead_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="SET NULL")
    )
    manager_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("managers.id", ondelete="SET NULL")
    )
    action_type: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
