"""SaaS billing and onboarding models. ТЗ «SaaS-слой» v1, раздел 2 (migration 060)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import TIMESTAMP, BigInteger, Boolean, ForeignKey, Integer, LargeBinary, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UpdatedAtMixin
from app.services.encryption import decrypt_pii, encrypt_pii


class SubscriptionPlan(CreatedAtMixin, Base):
    __tablename__ = "subscription_plans"

    id: Mapped[str] = mapped_column(Text, primary_key=True)  # start | pro | isolated
    name: Mapped[str] = mapped_column(Text, nullable=False)
    one_time_price: Mapped[int] = mapped_column(Integer, nullable=False)
    monthly_price: Mapped[int] = mapped_column(Integer, default=0)
    max_managers: Mapped[int] = mapped_column(Integer, default=3)
    max_cities: Mapped[int] = mapped_column(Integer, default=1)
    monthly_ai_budget: Mapped[int] = mapped_column(Integer, default=1500)
    bot_mode_allowed: Mapped[str] = mapped_column(Text, default="assist")
    features: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class BillingEvent(CreatedAtMixin, Base):
    __tablename__ = "billing_events"

    agency_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"))
    onboarding_request_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    amount_rub: Mapped[Optional[int]] = mapped_column(Integer)
    payment_method: Mapped[Optional[str]] = mapped_column(Text)
    payment_id: Mapped[Optional[str]] = mapped_column(Text)
    months_added: Mapped[int] = mapped_column(Integer, default=0)
    expires_at_after: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    note: Mapped[Optional[str]] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(Text, default="system")


class PlatformOperator(CreatedAtMixin, Base):
    __tablename__ = "platform_operators"

    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    username: Mapped[Optional[str]] = mapped_column(Text)
    display_name: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class OnboardingRequest(CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "onboarding_requests"

    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(Text)
    display_name: Mapped[Optional[str]] = mapped_column(Text)
    _phone_encrypted: Mapped[Optional[bytes]] = mapped_column("phone_encrypted", LargeBinary)
    city_name: Mapped[str] = mapped_column(Text, nullable=False)
    agency_name: Mapped[str] = mapped_column(Text, nullable=False)
    plan_id: Mapped[str] = mapped_column(Text, ForeignKey("subscription_plans.id"), default="start")
    status: Mapped[str] = mapped_column(Text, default="pending")
    payment_link: Mapped[Optional[str]] = mapped_column(Text)
    payment_id: Mapped[Optional[str]] = mapped_column(Text)
    agency_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="SET NULL"))
    operator_notes: Mapped[Optional[str]] = mapped_column(Text)

    @hybrid_property
    def phone(self) -> Optional[str]:
        return decrypt_pii(self._phone_encrypted) if self._phone_encrypted else None

    @phone.setter
    def phone(self, value: Optional[str]) -> None:
        self._phone_encrypted = encrypt_pii(value) if value else None
