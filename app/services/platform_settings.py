"""Settings an operator can change at runtime, without a deploy.

Only one so far: the AI provider. TZ 2.2 describes the providers as switchable
from the admin area and the acceptance checklist asks for it without a restart;
the value used to come from AI_DEFAULT_PROVIDER in .env, so switching meant
editing a file on the server and restarting the containers. Since the choice
between YandexGPT/GigaChat (data stays in Russia) and OpenAI/Anthropic (proxied,
anonymised prompt) is a 152-ФЗ decision, it should not need a deploy.

Reads are cached briefly: AIService asks on every call, and a database round trip
per AI request would be silly, while a stale answer for a few seconds is not.
"""
from __future__ import annotations

import time
from typing import Optional

import structlog
from sqlalchemy import text

logger = structlog.get_logger()

AI_PROVIDER = "ai_provider"
CACHE_TTL_SECONDS = 15

_cache: dict[str, tuple[float, Optional[str]]] = {}


def invalidate(key: str) -> None:
    _cache.pop(key, None)


async def get_setting(key: str) -> Optional[str]:
    """Stored value, or None. Never raises: a missing table must not stop AI."""
    hit = _cache.get(key)
    now = time.monotonic()
    if hit and now - hit[0] < CACHE_TTL_SECONDS:
        return hit[1]

    from app.database import async_session  # noqa: PLC0415

    value: Optional[str] = None
    try:
        async with async_session() as session:
            value = await session.scalar(
                text("SELECT value FROM platform_settings WHERE key = :k"), {"k": key}
            )
    except Exception as e:  # noqa: BLE001 - the setting is an override, not a dependency
        logger.warning("platform_settings unavailable", key=key, error=str(e))
        return None

    _cache[key] = (now, value)
    return value


async def set_setting(key: str, value: str, updated_by: Optional[str] = None) -> None:
    from app.database import async_session  # noqa: PLC0415

    async with async_session() as session:
        await session.execute(
            text(
                "INSERT INTO platform_settings (key, value, updated_by) "
                "VALUES (:k, :v, :by) "
                "ON CONFLICT (key) DO UPDATE SET value = :v, updated_by = :by, "
                "updated_at = now()"
            ),
            {"k": key, "v": value, "by": updated_by},
        )
        await session.commit()
    invalidate(key)
    logger.info("platform setting changed", key=key, value=value)
