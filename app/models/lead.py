"""Lead model (qualified contacts). Migration 001 table 6.

PII (name/phone/email) is stored encrypted (BYTEA) and exposed via hybrid
properties that transparently encrypt/decrypt (152-FZ, TZ section 8).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import TIMESTAMP, Boolean, ForeignKey, Integer, LargeBinary, Text
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UpdatedAtMixin
from app.services.encryption import decrypt_pii, encrypt_pii, phone_blind_index


class Lead(CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "leads"

    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False
    )
    geo_location_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("geo_locations.id", ondelete="SET NULL")
    )
    signal_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("signals.id", ondelete="SET NULL")
    )
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_platform: Mapped[Optional[str]] = mapped_column(Text)

    # Encrypted PII (BYTEA)
    _name_encrypted: Mapped[Optional[bytes]] = mapped_column("name_encrypted", LargeBinary)
    _phone_encrypted: Mapped[Optional[bytes]] = mapped_column("phone_encrypted", LargeBinary)
    _email_encrypted: Mapped[Optional[bytes]] = mapped_column("email_encrypted", LargeBinary)
    telegram_username: Mapped[Optional[str]] = mapped_column(Text)
    # Deterministic blind index for phone dedup (migration 003).
    phone_hash: Mapped[Optional[str]] = mapped_column(Text)

    consent_given: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_given_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    consent_text: Mapped[Optional[str]] = mapped_column(Text)
    consent_version: Mapped[str] = mapped_column(Text, default="1.0")
    consent_ip: Mapped[Optional[str]] = mapped_column(INET)
    consent_user_agent: Mapped[Optional[str]] = mapped_column(Text)

    segment: Mapped[Optional[str]] = mapped_column(Text)
    buyer_profile: Mapped[dict] = mapped_column(JSONB, default=dict)
    intent_score: Mapped[Optional[int]] = mapped_column(Integer)
    budget_min: Mapped[Optional[int]] = mapped_column(Integer)
    budget_max: Mapped[Optional[int]] = mapped_column(Integer)
    purchase_goal: Mapped[Optional[str]] = mapped_column(Text)
    urgency: Mapped[Optional[str]] = mapped_column(Text)
    lead_type: Mapped[str] = mapped_column(Text, default="buyer")
    alternative_seller_data: Mapped[Optional[dict]] = mapped_column(JSONB)
    assigned_to: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(Text, default="new")
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text)
    referred_to: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    ai_qualification: Mapped[dict] = mapped_column(JSONB, default=dict)

    @hybrid_property
    def name(self) -> Optional[str]:
        return decrypt_pii(self._name_encrypted) if self._name_encrypted else None

    @name.setter
    def name(self, value: Optional[str]) -> None:
        self._name_encrypted = encrypt_pii(value) if value else None

    @hybrid_property
    def phone(self) -> Optional[str]:
        return decrypt_pii(self._phone_encrypted) if self._phone_encrypted else None

    @phone.setter
    def phone(self, value: Optional[str]) -> None:
        self._phone_encrypted = encrypt_pii(value) if value else None
        self.phone_hash = phone_blind_index(value) if value else None

    @hybrid_property
    def email(self) -> Optional[str]:
        return decrypt_pii(self._email_encrypted) if self._email_encrypted else None

    @email.setter
    def email(self, value: Optional[str]) -> None:
        self._email_encrypted = encrypt_pii(value) if value else None
