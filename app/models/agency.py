"""Agency model (multi-tenant root). TZ section 7.2 / migration 001 table 1."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import TIMESTAMP, BigInteger, Boolean, Integer, LargeBinary, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, UpdatedAtMixin
from app.services.encryption import decrypt_pii, encrypt_pii

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
    onboarding_code: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Outbound CRM export (migration 007).
    crm_export_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    crm_type: Mapped[str | None] = mapped_column(Text)
    crm_webhook_url: Mapped[str | None] = mapped_column(Text)
    crm_field_mapping: Mapped[dict] = mapped_column(JSONB, default=dict)

    # SaaS layer (migration 060). Limits: NULL means "no limit" -- the agency
    # that predates billing must not wake up capped at three managers.
    subscription_active: Mapped[bool] = mapped_column(Boolean, default=True)
    subscription_expires_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    subscription_started_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    monthly_price_rub: Mapped[int] = mapped_column(Integer, default=0)
    one_time_price_rub: Mapped[int] = mapped_column(Integer, default=0)
    max_managers: Mapped[Optional[int]] = mapped_column(Integer)
    max_cities: Mapped[Optional[int]] = mapped_column(Integer)
    monthly_ai_budget_rub: Mapped[Optional[int]] = mapped_column(Integer)
    _telegram_bot_token_encrypted: Mapped[Optional[bytes]] = mapped_column(
        "telegram_bot_token_encrypted", LargeBinary)
    telegram_bot_username: Mapped[Optional[str]] = mapped_column(Text)
    telegram_webhook_secret: Mapped[Optional[str]] = mapped_column(Text)
    onboarding_completed_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    platform_notes: Mapped[Optional[str]] = mapped_column(Text)
    owner_telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    _owner_phone_encrypted: Mapped[Optional[bytes]] = mapped_column(
        "owner_phone_encrypted", LargeBinary)
    _owner_email_encrypted: Mapped[Optional[bytes]] = mapped_column(
        "owner_email_encrypted", LargeBinary)
    logo_url: Mapped[Optional[str]] = mapped_column(Text)
    brand_color: Mapped[Optional[str]] = mapped_column(Text)
    welcome_message: Mapped[Optional[str]] = mapped_column(Text)

    # AI sales bot (migration 062, ТЗ «AI-бот продажник» 2).
    bot_mode: Mapped[str] = mapped_column(Text, default="disabled")
    bot_reply_threshold: Mapped[int] = mapped_column(Integer, default=60)
    bot_semi_auto_delay: Mapped[int] = mapped_column(Integer, default=5)
    bot_daily_reply_limit: Mapped[int] = mapped_column(Integer, default=50)
    bot_tone_ab_test: Mapped[str] = mapped_column(Text, default="expert")
    bot_settings: Mapped[dict] = mapped_column(JSONB, default=dict)

    managers: Mapped[list["Manager"]] = relationship(
        back_populates="agency", cascade="all, delete-orphan"
    )

    # The bot token and the owner's contacts are secrets / personal data: stored
    # encrypted like every other one in the schema, never in plain text.
    @hybrid_property
    def telegram_bot_token(self) -> Optional[str]:
        enc = self._telegram_bot_token_encrypted
        return decrypt_pii(enc) if enc else None

    @telegram_bot_token.setter
    def telegram_bot_token(self, value: Optional[str]) -> None:
        self._telegram_bot_token_encrypted = encrypt_pii(value) if value else None

    @hybrid_property
    def owner_phone(self) -> Optional[str]:
        return decrypt_pii(self._owner_phone_encrypted) if self._owner_phone_encrypted else None

    @owner_phone.setter
    def owner_phone(self, value: Optional[str]) -> None:
        self._owner_phone_encrypted = encrypt_pii(value) if value else None

    @hybrid_property
    def owner_email(self) -> Optional[str]:
        return decrypt_pii(self._owner_email_encrypted) if self._owner_email_encrypted else None

    @owner_email.setter
    def owner_email(self, value: Optional[str]) -> None:
        self._owner_email_encrypted = encrypt_pii(value) if value else None
