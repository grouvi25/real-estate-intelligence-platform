"""Source discovery: candidates, run log, forum seeds. Migrations 063-064.

ТЗ «Сигналы» v1.0, апгрейд A. A candidate is what a searcher found; it becomes a
row in ``sources`` only once the sandbox test (or a manager) lets it in.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import TIMESTAMP, Boolean, Float, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DiscoveryCandidate(Base):
    __tablename__ = "discovery_candidates"

    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False)
    geo_location_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("geo_locations.id", ondelete="SET NULL"))
    platform: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[Optional[str]] = mapped_column(Text)
    url: Mapped[Optional[str]] = mapped_column(Text)
    rank_score: Mapped[Optional[float]] = mapped_column(Float)
    sandbox_score: Mapped[Optional[float]] = mapped_column(Float)
    verdict: Mapped[Optional[str]] = mapped_column(Text)
    is_alive: Mapped[Optional[bool]] = mapped_column(Boolean)
    decided_by: Mapped[str] = mapped_column(Text, default="discovery")
    source_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id", ondelete="SET NULL"))
    discovered_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now())
    tested_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    retry_after: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    raw_meta: Mapped[dict] = mapped_column(JSONB, default=dict)


class DiscoveryLog(Base):
    __tablename__ = "discovery_log"

    agency_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agencies.id", ondelete="CASCADE"))
    geo_location_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("geo_locations.id", ondelete="SET NULL"))
    run_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    city: Mapped[Optional[str]] = mapped_column(Text)
    found: Mapped[int] = mapped_column(Integer, default=0)
    passed_dup: Mapped[int] = mapped_column(Integer, default=0)
    tested: Mapped[int] = mapped_column(Integer, default=0)
    activated: Mapped[int] = mapped_column(Integer, default=0)
    sandboxed: Mapped[int] = mapped_column(Integer, default=0)
    rejected: Mapped[int] = mapped_column(Integer, default=0)
    by_platform: Mapped[dict] = mapped_column(JSONB, default=dict)
    errors: Mapped[dict] = mapped_column(JSONB, default=dict)
    duration_s: Mapped[Optional[float]] = mapped_column(Float)


class DiscoveryForumSeed(Base):
    __tablename__ = "discovery_forum_seeds"

    city: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
