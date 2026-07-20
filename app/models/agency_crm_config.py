"""Agency CRM connector config. Signal Bus addendum (migration 043).

Per-agency configuration for an external CRM connector (Topnlab, amoCRM,
Bitrix24, YUcrm). The API key is stored encrypted (Fernet BYTEA) and exposed via
a hybrid property, like other secrets.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, LargeBinary, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UpdatedAtMixin
from app.services.encryption import decrypt_pii, encrypt_pii


class AgencyCRMConfig(CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "agency_crm_config"
    __table_args__ = (UniqueConstraint("agency_id", "crm_type"),)

    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False
    )
    crm_type: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[Optional[str]] = mapped_column(Text)
    _api_key_encrypted: Mapped[Optional[bytes]] = mapped_column("api_key_encrypted", LargeBinary)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    field_mapping: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    @hybrid_property
    def api_key(self) -> Optional[str]:
        return decrypt_pii(self._api_key_encrypted) if self._api_key_encrypted else None

    @api_key.setter
    def api_key(self, value: Optional[str]) -> None:
        self._api_key_encrypted = encrypt_pii(value) if value else None
