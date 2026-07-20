"""Task model (manager to-dos). Migration 001 table 10."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import TIMESTAMP, Boolean, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UpdatedAtMixin


class Task(CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "tasks"

    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False
    )
    lead_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE")
    )
    manager_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("managers.id", ondelete="SET NULL")
    )
    task_type: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    suggested_message: Mapped[Optional[str]] = mapped_column(Text)
    due_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    status: Mapped[str] = mapped_column(Text, default="pending")
    completed_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    # SLA escalation (migration 004).
    is_urgent: Mapped[bool] = mapped_column(Boolean, default=False)
    escalated_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
