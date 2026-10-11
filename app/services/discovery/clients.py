"""One set of platform clients per discovery or health-check run.

Opened lazily, closed together. The Telegram client is taken only under the
shared Telethon lock (collection uses the same session file); if the lock is not
free within a minute, Telegram is simply unavailable for this run.
"""
from __future__ import annotations

from typing import Optional

import structlog

logger = structlog.get_logger()

USER_AGENT = ("Mozilla/5.0 (compatible; REIPBot/1.0; +https://reip.grouvi.online) "
              "AppleWebKit/537.36 (KHTML, like Gecko)")


class PlatformClients:
    def __init__(self, telegram_wait_seconds: float = 60):
        self._telegram_wait = telegram_wait_seconds
        self._tg_collector = None
        self._tg_lock_cm = None
        self._tg_tried = False
        self._vk = None
        self._yt = None
        self._http = None
        self._tg_guard = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()

    async def telegram(self):
        """A connected, authorised Telethon client, or None."""
        import asyncio  # noqa: PLC0415

        if self._tg_guard is None:
            self._tg_guard = asyncio.Lock()
        async with self._tg_guard:  # searchers and the sandbox ask concurrently
            return await self._telegram()

    async def _telegram(self):
        if self._tg_tried:
            return self._tg_collector._client if self._tg_collector else None
        self._tg_tried = True
        from app.collectors import telethon_sessions  # noqa: PLC0415
        from app.collectors.telegram_collector import TelegramCollector  # noqa: PLC0415

        session_name = await telethon_sessions.active_session()
        if session_name is None:
            return None
        collector = TelegramCollector(session_name)
        if not collector.is_available():
            return None
        cm = telethon_sessions.telethon_lock(wait_seconds=self._telegram_wait)
        got = await cm.__aenter__()
        if not got:
            await cm.__aexit__(None, None, None)
            logger.info("Discovery: Telegram busy, skipped this run")
            return None
        self._tg_lock_cm = cm
        try:
            if not await collector.is_authorized():
                await collector.close()
                return None
        except Exception as e:  # noqa: BLE001
            logger.warning("Discovery: Telegram unavailable", error=str(e)[:120])
            return None
        self._tg_collector = collector
        return collector._client

    def vk(self):
        from app.collectors.vk_collector import VkCollector  # noqa: PLC0415

        if self._vk is None:
            self._vk = VkCollector()
        return self._vk if self._vk.is_available() else None

    def youtube(self):
        from app.collectors.youtube_collector import YoutubeCollector  # noqa: PLC0415

        if self._yt is None:
            self._yt = YoutubeCollector()
        return self._yt if self._yt.is_available() else None

    async def http(self):
        import httpx  # noqa: PLC0415

        if self._http is None:
            self._http = httpx.AsyncClient(timeout=20, follow_redirects=True,
                                           headers={"User-Agent": USER_AGENT})
        return self._http

    async def close(self) -> None:
        for closer in (self._tg_collector, self._vk, self._yt):
            if closer is not None:
                try:
                    await closer.close()
                except Exception:  # noqa: BLE001
                    pass
        if self._http is not None:
            await self._http.aclose()
        if self._tg_lock_cm is not None:
            try:
                await self._tg_lock_cm.__aexit__(None, None, None)
            except Exception:  # noqa: BLE001
                pass
        self._tg_collector = self._vk = self._yt = self._http = self._tg_lock_cm = None


_ROBOTS: dict[str, Optional[object]] = {}


async def robots_allows(http, url: str) -> bool:
    """robots.txt of the site allows fetching ``url`` for our agent (and for
    everyone). A missing robots.txt allows; an unreadable one forbids."""
    from urllib.parse import urlsplit  # noqa: PLC0415
    from urllib.robotparser import RobotFileParser  # noqa: PLC0415

    parts = urlsplit(url)
    base = f"{parts.scheme}://{parts.netloc}"
    parser = _ROBOTS.get(base, False)
    if parser is False:
        parser = RobotFileParser()
        try:
            res = await http.get(base + "/robots.txt")
            if res.status_code >= 500:
                parser = None
            elif res.status_code >= 400:
                parser.parse([])
            else:
                parser.parse(res.text.splitlines())
        except Exception:  # noqa: BLE001
            parser = None
        _ROBOTS[base] = parser
    if parser is None:
        return False
    return parser.can_fetch("REIPBot", url) and parser.can_fetch("*", url)
