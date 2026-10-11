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

from contextlib import asynccontextmanager
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


# ---------------------------------------------------------------- один клиент

LOCK_KEY = "telethon:busy"
LOCK_TTL_SECONDS = 15 * 60  # дольше любого прохода: зависший процесс не держит вечно


@asynccontextmanager
async def telethon_lock(wait_seconds: float = 60):
    """Аккаунтом Telegram в один момент работает один процесс.

    Сессия Telethon — файл SQLite. Сбор (каждые 10 минут), автопоиск и проверка
    живости источников открывают один и тот же файл, и два клиента сразу дают
    «database is locked» и рваные запросы, за которые Telegram банит аккаунт
    быстрее. Отдаёт True, если замок взят; False — не дождались, работу с
    Telegram в этот раз надо пропустить. Недоступный Redis замок не держит:
    лучше рискнуть пересечением, чем остановить сбор целиком.
    """
    import asyncio  # noqa: PLC0415
    import secrets  # noqa: PLC0415
    import time  # noqa: PLC0415

    token = secrets.token_hex(8)
    try:
        client = await _redis()
    except Exception as e:  # noqa: BLE001
        logger.warning("Замок Telethon без Redis", error=str(e)[:120])
        yield True
        return
    acquired = False
    try:
        deadline = time.monotonic() + wait_seconds
        while True:
            try:
                acquired = bool(await client.set(LOCK_KEY, token, nx=True, ex=LOCK_TTL_SECONDS))
            except Exception as e:  # noqa: BLE001
                logger.warning("Замок Telethon без Redis", error=str(e)[:120])
                acquired = None
                break
            if acquired or time.monotonic() >= deadline:
                break
            await asyncio.sleep(2)
        yield acquired is not False
    finally:
        if acquired:
            try:
                if (await client.get(LOCK_KEY)) in (token, token.encode()):
                    await client.delete(LOCK_KEY)
            except Exception:  # noqa: BLE001
                pass
        await client.aclose()
