"""Agency model (multi-tenant root). TZ section 7.2 / migration 001 table 1."""
from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, UpdatedAtMixin

if TYPE_CHECKING:
    from app.models.manager import Manager


class Agency(CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "agencies"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    base_city: Mapped[str] = mapped_column(Text, nullable=False)
    subscription_plan: Mapped[str] = mapped_column(Text, default="mvp")
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)

    # The invitation is the token: a manager joins this agency only by presenting
    # it, and rotating it invalidates every link handed out before (migration 048).
    invite_token: Mapped[str | None] = mapped_column(Text)

    # Outbound CRM export (migration 007).
    crm_export_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    crm_type: Mapped[str | None] = mapped_column(Text)
    crm_webhook_url: Mapped[str | None] = mapped_column(Text)
    crm_field_mapping: Mapped[dict] = mapped_column(JSONB, default=dict)

    managers: Mapped[list["Manager"]] = relationship(
        back_populates="agency", cascade="all, delete-orphan"
    )
