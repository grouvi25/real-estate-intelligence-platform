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
from app.services.intent_scoring import content_fingerprint, quick_filter
from app.services.signal_bus import ingest_content

logger = structlog.get_logger()


def is_telethon_auth_error(error: BaseException) -> bool:
    """Recognize revoked sessions without making Telethon a mandatory import."""
    try:
        from telethon.errors import (
            AuthKeyDuplicatedError,
            AuthKeyUnregisteredError,
            SessionRevokedError,
            UserDeactivatedError,
        )
    except ImportError:
        return False
    return isinstance(error, (
        SessionRevokedError,
        AuthKeyUnregisteredError,
        AuthKeyDuplicatedError,
        UserDeactivatedError,
    ))


# Signal Bus addendum §2.1: origin_system says which SYSTEM produced the signal
# (open-source scouting here, the Content Engine later), not which platform --
# the platform is reply_channel. Storing the channel here made every source look
# like a separate system and left no way to tell scouting from content reactions.
ORIGIN_SCOUTING = "reip_scouting"

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


def _proxy_settings():
    """Разбирает socks5://host:port в вид, который понимает Telethon.

    Из Yandex Cloud дата-центры Telegram недоступны, и подключение уходит
    через SOCKS5 (см. config.telegram_proxy_url). Без настройки — None, то
    есть прямое подключение.
    """
    url = config.telegram_proxy_url
    if not url:
        return None
    rest = url.split("://", 1)[-1]
    host, _, port = rest.partition(":")
    return ("socks5", host, int(port or 1080))


def build_client(session_name: str | None = None):
    """Create a Telethon client with the project's connection settings applied."""
    from telethon import TelegramClient  # noqa: PLC0415

    client = TelegramClient(
        session_name or config.telethon_session_name,
        config.telethon_api_id,
        config.telethon_api_hash,
        proxy=_proxy_settings(),
    )
    if config.telethon_dc_port:
        force_dc_port(client, config.telethon_dc_port)
    return client


class TelegramCollector:
    def __init__(self, session_name: str | None = None):
        self.api_id = config.telethon_api_id
        self.api_hash = config.telethon_api_hash
        # Каким аккаунтом работать, решает очередь в telethon_sessions: упавший
        # помечен негодным и сюда уже не попадёт. Явное имя передаёт только тот,
        # кто знает, что делает — вход в новый аккаунт и тесты.
        self.session_name = session_name or config.telethon_session_name
        self._client = None

    def is_available(self) -> bool:
        return bool(self.api_id and self.api_hash)

    async def _get_client(self):
        if self._client is None:
            self._client = build_client(self.session_name)
            await self._client.connect()
        return self._client

    async def is_authorized(self) -> bool:
        """Есть ли за этим именем живой вход, а не пустой файл сессии.

        Имя аккаунта, под которым ещё ни разу не входили, Telethon молча заводит
        как новую пустую сессию — и сбор потом падает на каждом источнике по
        отдельности, вместо того чтобы сразу перейти к следующему аккаунту.
        """
        try:
            client = await self._get_client()
            return bool(await client.is_user_authorized())
        except Exception as e:  # noqa: BLE001
            logger.warning("Не проверить вход аккаунта",
                           session=self.session_name, error=str(e)[:120])
            return False

    @staticmethod
    def _username(source) -> Optional[str]:
        """Resolve a source to a Telegram username.

        Source Discovery stores the numeric chat id in external_id and the
        username in source_url (see discovery/source_finder.py). A bare numeric
        id cannot be resolved without its access_hash, so preferring external_id
        made every auto-found source fail with "Cannot find any entity
        corresponding to <id>" and the collector produced zero signals. A
        non-numeric external_id is still honoured -- that is a username for
        manually added sources.
        """
        external = str(source.external_id or "").lstrip("@").strip()
        if external and not external.isdigit():
            return external
        url = source.source_url or ""
        if "t.me/" in url:
            return url.split("t.me/")[-1].strip("/") or None
        return external or None

    # Each query is one API call and results dedupe by username, so a wider
    # sweep costs little and is the main lever on how many candidates exist
    # at all.
    MAX_QUERIES = 12

    async def search_sources(self, queries: list[str], limit: int = 10) -> list[dict]:
        """Search public chats/channels matching queries. Returns candidate dicts."""
        if not self.is_available():
            return []
        from telethon.tl.functions.contacts import SearchRequest  # noqa: PLC0415

        client = await self._get_client()
        seen: dict[str, dict] = {}
        for q in queries[:self.MAX_QUERIES]:
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

        await self._enrich_candidates(client, list(seen.values()))
        return list(seen.values())

    async def _enrich_candidates(self, client, candidates: list[dict], samples: int = 3) -> None:
        """Attach recent messages so the AI can judge a source by its content.

        The evaluation prompt asks for a description and sample messages, but the
        search only returns a title -- so scoring was done on the name alone and
        came out unstable: two chats both called "Барахолка Геленджик" scored 40
        and 0 in the same run. Mutates the candidates in place; a source that
        cannot be read is simply left without samples.
        """
        for cand in candidates:
            try:
                texts = []
                async for msg in client.iter_messages(cand["username"], limit=samples * 4):
                    text = (getattr(msg, "message", None) or "").strip()
                    if len(text) > 20:
                        texts.append(text[:280])
                    if len(texts) >= samples:
                        break
                cand["samples"] = texts
            except Exception as e:  # noqa: BLE001 - private, deleted or rate-limited
                logger.debug("Could not sample source", username=cand["username"], error=str(e))

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
                # ...and one per distinct body: the same listing gets reposted
                # across chats and days with a new message id each time, which
                # put one advert into the live queue five times over.
                fingerprint = content_fingerprint(text)
                duplicate = await session.scalar(
                    select(Signal.id).where(
                        Signal.agency_id == source.agency_id,
                        Signal.content_fingerprint == fingerprint,
                    )
                )
                if duplicate:
                    continue
                norm = adapter.normalize(raw)
                session.add(Signal(
                    agency_id=source.agency_id,
                    source_id=source.id,
                    geo_location_id=source.geo_location_id,
                    content_unit_id=cu.id,
                    raw_text=text,
                    content_fingerprint=fingerprint,
                    author_hash=norm.author_hash,
                    author_display_name=norm.author_display_name,
                    signal_url=raw["url"],
                    origin_system=ORIGIN_SCOUTING,
                    reply_channel="tg_bot",
                    status="new",
                ))
                created += 1
            await session.commit()
        except Exception as e:  # noqa: BLE001
            if is_telethon_auth_error(e):
                raise
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
