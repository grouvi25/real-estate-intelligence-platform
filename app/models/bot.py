"""AI sales bot models. ТЗ «AI-бот продажник» v1, раздел 2 (migration 062)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import TIMESTAMP, BigInteger, Boolean, Float, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UpdatedAtMixin


class BotConversation(CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "bot_conversations"

    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False)
    user_platform: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(Text)
    display_name: Mapped[Optional[str]] = mapped_column(Text)
    state: Mapped[str] = mapped_column(Text, default="greeting")
    history: Mapped[list] = mapped_column(JSONB, default=list)
    collected_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    lead_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="SET NULL"))
    signal_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("signals.id", ondelete="SET NULL"))
    bot_mode: Mapped[str] = mapped_column(Text, default="assist")
    tone_variant: Mapped[str] = mapped_column(Text, default="expert")
    last_user_msg_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    reminded_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))


class BotPublicReply(CreatedAtMixin, Base):
    __tablename__ = "bot_public_replies"

    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False)
    signal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("signals.id", ondelete="CASCADE"), nullable=False)
    reply_text: Mapped[str] = mapped_column(Text, nullable=False)
    tone_variant: Mapped[str] = mapped_column(Text, default="expert")
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, default="draft")
    fail_reason: Mapped[Optional[str]] = mapped_column(Text)
    scheduled_for: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    sent_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    sent_by: Mapped[Optional[str]] = mapped_column(Text)
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("managers.id", ondelete="SET NULL"))
    got_response: Mapped[bool] = mapped_column(Boolean, default=False)
    converted_to_lead: Mapped[bool] = mapped_column(Boolean, default=False)


class BotLearningPool(CreatedAtMixin, Base):
    __tablename__ = "bot_learning_pool"

    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False)
    conversation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bot_conversations.id", ondelete="CASCADE"), unique=True)
    tone_variant: Mapped[Optional[str]] = mapped_column(Text)
    scenario: Mapped[list] = mapped_column(JSONB, nullable=False)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
