"""Demo mode settings. Migration 067 (ТЗ «Сигналы» v1.0, апгрейд C)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import TIMESTAMP, BigInteger, Boolean, Integer, Text, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DemoConfig(Base):
    __tablename__ = "demo_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    demo_city: Mapped[str] = mapped_column(Text, default="Краснодар")
    session_ttl_min: Mapped[int] = mapped_column(Integer, default=30)
    headline: Mapped[str] = mapped_column(Text)
    allowed_tabs: Mapped[list] = mapped_column(ARRAY(Text))
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    updated_by: Mapped[Optional[int]] = mapped_column(BigInteger)
