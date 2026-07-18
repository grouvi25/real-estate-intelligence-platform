"""Agency model (multi-tenant root). TZ section 7.2 / migration 001 table 1."""
from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.manager import Manager


class Agency(Base):
    __tablename__ = "agencies"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    base_city: Mapped[str] = mapped_column(Text, nullable=False)
    subscription_plan: Mapped[str] = mapped_column(Text, default="mvp")
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)

    managers: Mapped[list["Manager"]] = relationship(
        back_populates="agency", cascade="all, delete-orphan"
    )
