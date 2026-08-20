"""Очередь аккаунтов Telegram для сбора: основной, за ним резервные.

Аккаунт для сбора — расходник. Его могут заблокировать, и до сих пор это
означало полную остановку Telegram-сбора до тех пор, пока человек не дойдёт до
сервера и не авторизует новый вручную. Здесь список аккаунтов вместо одного:
упавший помечается негодным, работа продолжается со следующего.

Пометка живёт в Redis, а не в памяти процесса: воркеров несколько, и узнать о
блокировке они должны все сразу, а не каждый на своей ошибке. Она бессрочная —
заблокированный аккаунт сам не воскреснет, и молчаливый возврат к нему через
час означал бы новый круг ошибок. Снимается либо руками, либо когда для этого
аккаунта заводят новую сессию.
"""
from __future__ import annotations

from typing import Optional

import structlog

from app.config import config

logger = structlog.get_logger()

DEAD_KEY = "telethon:session:dead:{}"


def sessions() -> list[str]:
    """Аккаунты в порядке предпочтения: первый — основной."""
    raw = (config.telethon_sessions_raw or "").strip()
    names = [n.strip() for n in raw.split(",") if n.strip()] if raw else []
    if not names:
        names = [config.telethon_session_name]
    # Один и тот же аккаунт, записанный дважды, — не резерв, а грабли: сбор
    # дважды упал бы на одном и том же и решил, что резерв кончился.
    seen: set[str] = set()
    return [n for n in names if not (n in seen or seen.add(n))]


async def _redis():
    import redis.asyncio as redis  # noqa: PLC0415

    return redis.from_url(config.redis_url, socket_connect_timeout=2, socket_timeout=2)


async def dead_sessions() -> set[str]:
    client = await _redis()
    try:
        out = set()
        for name in sessions():
            if await client.get(DEAD_KEY.format(name)):
                out.add(name)
        return out
    except Exception as e:  # noqa: BLE001 - недоступный Redis не повод стоять
        logger.warning("Не прочитать состояние аккаунтов", error=str(e)[:120])
        return set()
    finally:
        await client.aclose()


async def alive_sessions() -> list[str]:
    dead = await dead_sessions()
    return [n for n in sessions() if n not in dead]


async def active_session() -> Optional[str]:
    """Аккаунт, которым работать прямо сейчас. None — живых не осталось."""
    alive = await alive_sessions()
    return alive[0] if alive else None


async def mark_dead(name: str, error: BaseException | str) -> None:
    client = await _redis()
    try:
        await client.set(DEAD_KEY.format(name), str(error)[:200])
    except Exception as e:  # noqa: BLE001
        logger.error("Не сохранить пометку о негодном аккаунте", error=str(e)[:120])
    finally:
        await client.aclose()
    logger.error("Аккаунт Telegram выбыл", session=name,
                 error=str(error)[:120], осталось=len(await alive_sessions()))


async def revive(name: Optional[str] = None) -> int:
    """Снять пометку — со всех аккаунтов или с одного. Возвращает сколько сняли."""
    client = await _redis()
    try:
        names = [name] if name else sessions()
        return sum([bool(await client.delete(DEAD_KEY.format(n))) for n in names])
    except Exception as e:  # noqa: BLE001
        logger.error("Не снять пометку", error=str(e)[:120])
        return 0
    finally:
        await client.aclose()
