"""Collector Celery tasks. TZ section 15 + Signal Bus.

Periodically pulls new messages from active Telegram sources through the
TelegramCollector, turning them into content_units + signals. No-op when no
Telethon session is configured.
"""
from __future__ import annotations

from datetime import datetime, timezone

import structlog
from celery import shared_task

from worker.async_runner import run_async

logger = structlog.get_logger()


def _telethon_auth_errors() -> tuple[type[BaseException], ...]:
    """Load Telethon lazily so workers and CI can start without that optional client."""
    try:
        from telethon.errors import (
            AuthKeyDuplicatedError,
            AuthKeyUnregisteredError,
            SessionRevokedError,
            UserDeactivatedError,
        )
    except ImportError:
        return ()
    return (
        SessionRevokedError,
        AuthKeyUnregisteredError,
        AuthKeyDuplicatedError,
        UserDeactivatedError,
    )
TELETHON_PAUSED_KEY = "telethon:paused_until"
TELETHON_PAUSE_HOURS = 6


async def _is_telethon_paused() -> bool:
    """Return whether an authentication failure currently suppresses collection."""
    import redis.asyncio as redis

    from app.config import config

    client = redis.from_url(config.redis_url, socket_connect_timeout=2, socket_timeout=2)
    try:
        return bool(await client.get(TELETHON_PAUSED_KEY))
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not read Telethon pause state", error=str(e))
        return False
    finally:
        await client.aclose()


async def _clear_telethon_pause() -> None:
    """Снять паузу сбора. Вызывается, когда работать снова есть кем."""
    import redis.asyncio as redis  # noqa: PLC0415

    from app.config import config  # noqa: PLC0415

    client = redis.from_url(config.redis_url, socket_connect_timeout=2, socket_timeout=2)
    try:
        await client.delete(TELETHON_PAUSED_KEY)
    except Exception as e:  # noqa: BLE001
        logger.warning("Не снять паузу сбора", error=str(e)[:120])
    finally:
        await client.aclose()


async def _switch_or_pause(session_name: str, error: BaseException) -> bool:
    """Пометить аккаунт негодным и сказать, есть ли кем продолжать.

    Заблокированный аккаунт больше не берётся в работу. Пока в очереди остаётся
    хоть один живой, сбор продолжается им же, в этом самом заходе — человек
    узнаёт из оповещения, но чинить ничего не должен. Пауза и тревога остаются
    на случай, когда закончились все.
    """
    from app.collectors import telethon_sessions  # noqa: PLC0415
    from app.services.alerts import send_critical_alert  # noqa: PLC0415

    await telethon_sessions.mark_dead(session_name, error)
    alive = await telethon_sessions.alive_sessions()
    if alive:
        logger.warning("Аккаунт Telegram заблокирован, перехожу на резервный",
                       выбыл=session_name, продолжаю=alive[0], осталось=len(alive))
        try:
            await send_critical_alert(
                f"""⚠️ Аккаунт Telegram выбыл из сбора.
Был: {session_name}
Продолжаю резервным: {alive[0]} (в запасе ещё {len(alive) - 1})
Сбор не останавливался."""
            )
        except Exception as alert_error:  # noqa: BLE001
            logger.error("Не отправить оповещение о смене аккаунта", error=str(alert_error))
        return True

    await _pause_telethon(error)
    return False


async def _pause_telethon(error: BaseException) -> None:
    """Pause noisy retries and alert the operator that re-authorization is needed."""
    import redis.asyncio as redis

    from app.config import config
    from app.services.alerts import send_critical_alert

    client = redis.from_url(config.redis_url, socket_connect_timeout=2, socket_timeout=2)
    try:
        await client.setex(TELETHON_PAUSED_KEY, TELETHON_PAUSE_HOURS * 3600, "1")
    except Exception as redis_error:  # noqa: BLE001
        logger.error("Could not persist Telethon pause", error=str(redis_error))
    finally:
        await client.aclose()

    logger.error(
        "Telethon session error - collection paused",
        error=type(error).__name__,
        pause_hours=TELETHON_PAUSE_HOURS,
    )
    try:
        await send_critical_alert(
            f"""🚨 Telegram-аккаунты для сбора закончились — живых не осталось.
Сбор приостановлен на {TELETHON_PAUSE_HOURS}ч.
Нужен новый аккаунт: вход через scripts/telethon_login.py."""
        )
    except Exception as alert_error:  # noqa: BLE001
        logger.error("Could not send Telethon re-auth alert", error=str(alert_error))


def _stamp(src) -> None:
    """Remember that this source was visited, whatever came of it.

    The column and the API field for it shipped from the start and nothing ever
    wrote to either, so "last checked" was null on every source and the only way
    to tell a working collector from a stopped one was to read the worker's log.
    Stamped before the fetch so a source that fails is still visibly attempted.
    """
    src.last_checked_at = datetime.now(timezone.utc)


async def _collect_telegram_sources(limit_per_source: int = 50) -> int:
    from sqlalchemy import select

    from app.collectors import telethon_sessions
    from app.collectors.telegram_collector import TelegramCollector
    from app.database import async_session
    from app.models.geo_location import GeoLocation
    from app.models.source import Source

    # Пауза ставится, только когда работать было нечем. Если с тех пор в очереди
    # появился живой аккаунт — держать её незачем: иначе новый аккаунт завели, а
    # сбор всё равно стоит до конца шести часов и никто не понимает почему.
    if await _is_telethon_paused():
        if await telethon_sessions.active_session() is None:
            logger.info("Telethon collection skipped: paused after auth error")
            return 0
        await _clear_telethon_pause()
        logger.info("Пауза снята: в очереди появился живой аккаунт")

    # Аккаунт для сбора расходный: заблокируют — берём следующий из очереди, и
    # берём здесь же, а не через десять минут до следующего запуска. Попыток не
    # больше, чем аккаунтов, иначе на общей поломке связи мы бы перебрали и
    # пометили негодными все до единого.
    for _ in range(len(telethon_sessions.sessions())):
        session_name = await telethon_sessions.active_session()
        if session_name is None:
            logger.warning("Живых аккаунтов Telegram не осталось")
            return 0

        collector = TelegramCollector(session_name)
        if not collector.is_available():
            logger.info("Telegram collector not configured; skipping")
            return 0

        # Аккаунт без входа — такой же выбывший, как заблокированный: работать
        # им нельзя, и держать его первым в очереди значит стоять на месте.
        if not await collector.is_authorized():
            await telethon_sessions.mark_dead(session_name, "нет входа в аккаунт")
            try:
                await collector.close()
            except Exception:  # noqa: BLE001
                pass
            continue

        total = 0
        try:
            async with async_session() as session:
                sources = (await session.execute(
                    select(Source).where(
                        Source.status.in_(("active", "sandbox")),
                        Source.source_type.in_(("telegram_chat", "telegram_channel")),
                    )
                )).scalars().all()
                for src in sources:
                    keywords = {}
                    if src.geo_location_id:
                        geo = await session.get(GeoLocation, src.geo_location_id)
                        keywords = (geo.keywords if geo else {}) or {}
                    _stamp(src)
                    total += await collector.collect_from_source(
                        session, src, keywords, limit=limit_per_source)
                await session.commit()
        except _telethon_auth_errors() as e:
            # Не остановка, а смена аккаунта: _switch_or_pause скажет, есть ли кем
            # продолжать, и сам поставит паузу, когда живых не осталось.
            switched = await _switch_or_pause(session_name, e)
            if not switched:
                return 0
            continue
        except Exception as e:  # noqa: BLE001
            logger.warning("Telethon collection failed",
                           error=str(e), error_type=type(e).__name__)
            return 0
        finally:
            try:
                await collector.close()
            except Exception as e:  # noqa: BLE001 - закрытие не должно ничего решать
                logger.warning("Telethon collector close failed", error=str(e))

        logger.info("Telegram collection run complete", signals=total, account=session_name)
        return total

    logger.warning("Все аккаунты Telegram выбыли за один заход")
    return 0


@shared_task(name="worker.tasks.collector_tasks.collect_telegram_sources")
def collect_telegram_sources(limit_per_source: int = 50) -> int:
    return run_async(_collect_telegram_sources(limit_per_source))


async def _collect_vk_sources(limit_per_source: int = 50) -> int:
    """Read VK groups the same way Telegram chats are read.

    Nothing called the VK API before this, so a vk_group source -- whether found
    by discovery or added by hand on the Источники screen -- was simply skipped
    and produced nothing, silently.
    """
    from sqlalchemy import select

    from app.collectors.vk_collector import VkCollector
    from app.database import async_session
    from app.models.geo_location import GeoLocation
    from app.models.source import Source

    collector = VkCollector()
    if not collector.is_available():
        logger.info("VK collector not configured; skipping")
        return 0

    total = 0
    try:
        async with async_session() as session:
            sources = (await session.execute(
                select(Source).where(
                    Source.status.in_(("active", "sandbox")),
                    Source.source_type == "vk_group",
                )
            )).scalars().all()
            for src in sources:
                keywords = {}
                if src.geo_location_id:
                    geo = await session.get(GeoLocation, src.geo_location_id)
                    keywords = (geo.keywords if geo else {}) or {}
                _stamp(src)
                total += await collector.collect_from_source(
                    session, src, keywords, limit=limit_per_source)
            # The stamp has to survive a source that threw before its own commit.
            await session.commit()
    finally:
        await collector.close()
    logger.info("VK collection run complete", signals=total)
    return total


@shared_task(name="worker.tasks.collector_tasks.collect_vk_sources")
def collect_vk_sources(limit_per_source: int = 50) -> int:
    return run_async(_collect_vk_sources(limit_per_source))


async def _collect_web_sources(limit_per_source: int = 50) -> int:
    """Read the sources that are neither a chat nor a group: feeds and YouTube.

    Both source types were allowed by the schema from the first migration and
    nothing ever read one, so a feed added on the Источники screen sat there for
    ever. YouTube stays a no-op without YOUTUBE_API_KEY; a feed needs no key, so
    the source list is its only switch.
    """
    from sqlalchemy import select

    from app.collectors.rss_collector import RssCollector
    from app.collectors.youtube_collector import YoutubeCollector
    from app.database import async_session
    from app.models.geo_location import GeoLocation
    from app.models.source import Source

    rss, youtube = RssCollector(), YoutubeCollector()
    # A forum is read as a feed: the ones worth watching publish one, and a
    # source nobody collects is worse than one that quietly finds nothing.
    by_type = {("rss", "website", "forum"): rss, ("youtube",): youtube}

    total = 0
    try:
        async with async_session() as session:
            sources = (await session.execute(
                select(Source).where(
                    Source.status.in_(("active", "sandbox")),
                    Source.source_type.in_(("rss", "website", "forum", "youtube")),
                )
            )).scalars().all()
            for src in sources:
                collector = next(
                    (c for types, c in by_type.items() if src.source_type in types), None)
                if collector is None or not collector.is_available():
                    continue
                keywords = {}
                if src.geo_location_id:
                    geo = await session.get(GeoLocation, src.geo_location_id)
                    keywords = (geo.keywords if geo else {}) or {}
                _stamp(src)
                total += await collector.collect_from_source(
                    session, src, keywords, limit=limit_per_source)
            # The stamp has to survive a source that threw before its own commit.
            await session.commit()
    finally:
        await rss.close()
        await youtube.close()
    logger.info("Web collection run complete", signals=total)
    return total


@shared_task(name="worker.tasks.collector_tasks.collect_web_sources")
def collect_web_sources(limit_per_source: int = 50) -> int:
    return run_async(_collect_web_sources(limit_per_source))
