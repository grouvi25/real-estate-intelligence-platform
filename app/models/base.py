"""Declarative base + timestamp mixins.

Not every table has both created_at and updated_at (see migration 001), so the
timestamp columns are opt-in mixins rather than baked into Base:
- Base:            id (UUID PK) only
- CreatedAtMixin:  created_at
- UpdatedAtMixin:  updated_at
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )


class UpdatedAtMixin:
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
