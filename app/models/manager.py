"""Manager model (multi-platform: Telegram + MAX). TZ section 7.2 / migration 001 table 9.

Phone/email are PII and are stored encrypted (BYTEA) with transparent
encrypt/decrypt via hybrid properties, per 152-FZ (TZ section 8).
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import BigInteger, Boolean, ForeignKey, LargeBinary, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.agency import Agency
from app.models.base import Base, CreatedAtMixin, UpdatedAtMixin
from app.services.encryption import decrypt_pii, encrypt_pii


class Manager(CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "managers"

    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger, unique=True)
    max_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, unique=True)
    preferred_platform: Mapped[str] = mapped_column(Text, default="telegram")
    role: Mapped[str] = mapped_column(Text, default="manager")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Encrypted PII (BYTEA)
    _phone_encrypted: Mapped[Optional[bytes]] = mapped_column("phone_encrypted", LargeBinary)
    _email_encrypted: Mapped[Optional[bytes]] = mapped_column("email_encrypted", LargeBinary)

    agency: Mapped[Agency] = relationship(back_populates="managers")

    @hybrid_property
    def phone(self) -> Optional[str]:
        return decrypt_pii(self._phone_encrypted) if self._phone_encrypted else None

    @phone.setter
    def phone(self, value: Optional[str]) -> None:
        self._phone_encrypted = encrypt_pii(value) if value else None

    @hybrid_property
    def email(self) -> Optional[str]:
        return decrypt_pii(self._email_encrypted) if self._email_encrypted else None

    @email.setter
    def email(self, value: Optional[str]) -> None:
        self._email_encrypted = encrypt_pii(value) if value else None
