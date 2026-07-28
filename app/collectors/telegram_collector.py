"""Telegram collector (Telethon userbot). TZ section 15 + Signal Bus.

Reads messages from monitored Telegram sources and searches for new candidate
sources. Credential-gated: without TELETHON_API_ID/HASH it reports unavailable
and all methods degrade to no-ops, so the app/CI run without a live session.

Telethon is imported lazily (a live session requires interactive login, which is
provisioned out-of-band), keeping this module importable everywhere.
"""
from __future__ import annotations

from typing import Any, Optional

import structlog

from app.config import config
from app.services.channels import get_channel_adapter
from app.services.intent_scoring import quick_filter
from app.services.signal_bus import ingest_content

logger = structlog.get_logger()

# Telegram serves MTProto on 443, 80 and 5222. The production host cannot reach
# 149.154.167.0/24 (DC2 + DC4) on 443 or 80 -- those connections time out -- while
# 5222 completes the handshake, and the other DCs answer on 443 normally. Telethon
# starts on DC2, so it hung on "Attempt N at connecting failed: TimeoutError".
# TELETHON_DC_PORT pins an alternative port; the default keeps Telethon's own.
def force_dc_port(client, port: int) -> None:
    """Pin every DC connection to ``port``, including after a DC migration.

    Telethon re-reads addresses from the server's DC options on migration, which
    always name 443, so overriding the session once is not enough.
    """
    session = client.session
    original_set_dc = session.set_dc

    def set_dc(dc_id, ip, _port_from_server):
        original_set_dc(dc_id, ip, port)

    session.set_dc = set_dc
    session.set_dc(session.dc_id, session.server_address, port)


def build_client(session_name: str | None = None):
    """Create a Telethon client with the project's connection settings applied."""
    from telethon import TelegramClient  # noqa: PLC0415

    client = TelegramClient(
        session_name or config.telethon_session_name,
        config.telethon_api_id,
        config.telethon_api_hash,
    )
    if config.telethon_dc_port:
        force_dc_port(client, config.telethon_dc_port)
    return client


class TelegramCollector:
    def __init__(self):
        self.api_id = config.telethon_api_id
        self.api_hash = config.telethon_api_hash
        self.session_name = config.telethon_session_name
        self._client = None

    def is_available(self) -> bool:
        return bool(self.api_id and self.api_hash)

    async def _get_client(self):
        if self._client is None:
            self._client = build_client(self.session_name)
            await self._client.connect()
        return self._client

    @staticmethod
    def _username(source) -> Optional[str]:
        if source.external_id:
            return str(source.external_id).lstrip("@")
        url = source.source_url or ""
        if "t.me/" in url:
            return url.split("t.me/")[-1].strip("/")
        return None

    async def search_sources(self, queries: list[str], limit: int = 10) -> list[dict]:
        """Search public chats/channels matching queries. Returns candidate dicts."""
        if not self.is_available():
            return []
        from telethon.tl.functions.contacts import SearchRequest  # noqa: PLC0415

        client = await self._get_client()
        seen: dict[str, dict] = {}
        for q in queries[:5]:
            try:
                res = await client(SearchRequest(q=q, limit=limit))
            except Exception as e:  # noqa: BLE001
                logger.warning("Telegram search failed", query=q, error=str(e))
                continue
            for chat in getattr(res, "chats", []):
                username = getattr(chat, "username", None)
                if not username:
                    continue
                seen[username] = {
                    "id": str(chat.id),
                    "name": getattr(chat, "title", username),
                    "username": username,
                    "url": f"https://t.me/{username}",
                    "members": getattr(chat, "participants_count", 0) or 0,
                    "description": "",
                    "samples": [],
                }
        return list(seen.values())

    async def collect_from_source(
        self, session, source, geo_keywords: dict[str, Any], limit: int = 50
    ) -> int:
        """Ingest recent messages from a source; create signals for promising ones.

        Returns the number of new signals created.
        """
        if not self.is_available():
            return 0
        from sqlalchemy import select  # noqa: PLC0415

        from app.models.signal import Signal  # noqa: PLC0415

        username = self._username(source)
        if not username:
            return 0

        adapter = get_channel_adapter("telegram")
        client = await self._get_client()
        created = 0
        try:
            async for msg in client.iter_messages(username, limit=limit):
                text = getattr(msg, "message", None)
                if not text:
                    continue
                sender = await msg.get_sender() if msg.sender_id else None
                raw = {
                    "message_id": msg.id,
                    "chat": {"id": getattr(msg, "chat_id", None)},
                    "from": {"id": msg.sender_id,
                             "username": getattr(sender, "username", None)},
                    "text": text,
                    "date": msg.date.timestamp() if msg.date else None,
                    "url": f"https://t.me/{username}/{msg.id}",
                }
                cu = await ingest_content(session, source.agency_id, "telegram", raw,
                                          source_id=source.id)
                if cu is None:
                    continue
                # One signal per content unit.
                exists = await session.scalar(
                    select(Signal.id).where(Signal.content_unit_id == cu.id))
                if exists:
                    continue
                if not quick_filter(text, geo_keywords):
                    continue
                norm = adapter.normalize(raw)
                session.add(Signal(
                    agency_id=source.agency_id,
                    source_id=source.id,
                    geo_location_id=source.geo_location_id,
                    content_unit_id=cu.id,
                    raw_text=text,
                    author_hash=norm.author_hash,
                    author_display_name=norm.author_display_name,
                    signal_url=raw["url"],
                    origin_system="telegram",
                    reply_channel="telegram",
                    status="new",
                ))
                created += 1
            await session.commit()
        except Exception as e:  # noqa: BLE001
            logger.warning("Telegram collect failed", source=username, error=str(e))
        logger.info("Telegram collect", source=username, signals_created=created)
        return created

    async def close(self) -> None:
        if self._client is not None:
            await self._client.disconnect()
            self._client = None


async def search_candidate_sources(queries: list[str], limit: int = 10) -> list[dict]:
    """Module-level helper used by Source Discovery (source_finder)."""
    collector = TelegramCollector()
    try:
        return await collector.search_sources(queries, limit=limit)
    finally:
        await collector.close()
