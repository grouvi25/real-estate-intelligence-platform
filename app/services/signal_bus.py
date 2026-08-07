"""Signal Bus service. Signal Bus addendum.

Ties channel adapters, content units and signals together:
- ingest_content(): normalize a raw channel payload and upsert a ContentUnit.
- send_signal_reply(): deliver a manager's reply draft on the originating
  channel and record the outcome on the signal.

Kept dependency-light; DB session is passed in so this composes with routers and
Celery tasks alike.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import select

from app.models.content_unit import ContentUnit
from app.services.channels import get_channel_adapter

logger = structlog.get_logger()


async def ingest_content(
    session,
    agency_id: uuid.UUID,
    channel: str,
    raw: dict,
    source_id: Optional[uuid.UUID] = None,
) -> Optional[ContentUnit]:
    """Normalize a raw channel payload and upsert its ContentUnit.

    Dedup is by (agency, channel, external_id). Returns the stored ContentUnit,
    or None if the channel is unknown.
    """
    adapter = get_channel_adapter(channel)
    if adapter is None:
        logger.warning("ingest_content: unknown channel", channel=channel)
        return None

    norm = adapter.normalize(raw)

    existing = None
    if norm.external_id is not None:
        existing = (
            await session.execute(
                select(ContentUnit).where(
                    ContentUnit.agency_id == agency_id,
                    ContentUnit.channel == norm.channel,
                    ContentUnit.external_id == norm.external_id,
                )
            )
        ).scalars().first()

    if existing is not None:
        existing.raw_content = norm.raw_content
        existing.url = norm.url or existing.url
        cu = existing
    else:
        cu = ContentUnit(
            agency_id=agency_id,
            source_id=source_id,
            channel=norm.channel,
            external_id=norm.external_id,
            url=norm.url,
            content_type=norm.content_type,
            raw_content=norm.raw_content,
            author_hash=norm.author_hash,
            author_display_name=norm.author_display_name,
            published_at=norm.published_at,
            meta=norm.meta,
        )
        session.add(cu)
    await session.flush()
    return cu


async def send_signal_reply(session, signal, manager_id: Optional[str] = None) -> dict:
    """Deliver signal.reply_draft on the originating channel; update the signal."""
    if not signal.reply_draft:
        return {"sent": False, "reason": "no_draft"}

    channel = signal.reply_channel or signal.origin_system
    cu = None
    if signal.content_unit_id is not None:
        cu = await session.get(ContentUnit, signal.content_unit_id)
    if channel is None and cu is not None:
        channel = cu.channel

    adapter = get_channel_adapter(channel or "")
    if adapter is None:
        signal.reply_status = "skipped"
        await session.commit()
        return {"sent": False, "reason": "unknown_channel", "channel": channel}
    if not adapter.reply_supported():
        # The adapter explains itself: Avito and ЦИАН need the agency's own
        # professional account, a feed has no reply surface at all. "skipped"
        # alone told the manager nothing about what to do with the draft.
        signal.reply_status = "skipped"
        await session.commit()
        result = await adapter.send_reply("", signal.reply_draft)
        logger.info("Signal reply not sent", signal_id=str(signal.id),
                    channel=channel, reason=result.get("reason"))
        return result

    target = cu.external_id if cu else None
    if not target:
        signal.reply_status = "failed"
        await session.commit()
        return {"sent": False, "reason": "no_target", "channel": channel}

    result = await adapter.send_reply(target, signal.reply_draft)
    # 'replied' is the addendum's word for a delivered answer (§5.2).
    signal.reply_status = "replied" if result.get("sent") else "failed"
    signal.replied_at = datetime.now(timezone.utc)
    if manager_id:
        signal.replied_by_manager_id = uuid.UUID(str(manager_id))
    await session.commit()
    logger.info("Signal reply sent", signal_id=str(signal.id), status=signal.reply_status)
    return result
