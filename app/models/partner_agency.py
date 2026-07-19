"""Partner agency model. Migration 001 table 11.

contact_phone is PII -> stored encrypted (BYTEA) with a hybrid property.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import Boolean, Float, ForeignKey, Integer, LargeBinary, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UpdatedAtMixin
from app.services.encryption import decrypt_pii, encrypt_pii


class PartnerAgency(CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "partner_agencies"

    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False
    )
    partner_name: Mapped[str] = mapped_column(Text, nullable=False)
    partner_city: Mapped[str] = mapped_column(Text, nullable=False)
    partner_region: Mapped[Optional[str]] = mapped_column(Text)
    contact_name: Mapped[Optional[str]] = mapped_column(Text)
    contact_telegram: Mapped[Optional[str]] = mapped_column(Text)
    _contact_phone_encrypted: Mapped[Optional[bytes]] = mapped_column(
        "contact_phone_encrypted", LargeBinary
    )
    commission_percent: Mapped[Optional[float]] = mapped_column(Float)
    commission_fixed: Mapped[Optional[int]] = mapped_column(Integer)
    commission_type: Mapped[str] = mapped_column(Text, default="percent")
    trust_level: Mapped[str] = mapped_column(Text, default="standard")
    deals_count: Mapped[int] = mapped_column(Integer, default=0)
    total_commission_earned: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    @hybrid_property
    def contact_phone(self) -> Optional[str]:
        return decrypt_pii(self._contact_phone_encrypted) if self._contact_phone_encrypted else None

    @contact_phone.setter
    def contact_phone(self, value: Optional[str]) -> None:
        self._contact_phone_encrypted = encrypt_pii(value) if value else None
