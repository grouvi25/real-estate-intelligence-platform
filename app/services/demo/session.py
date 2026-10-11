"""Demo sessions, demo settings and demo data -- all in Redis. ТЗ «Сигналы» 7.2.

    demo:session:{uuid}           {"city", "created_at", "role": "demo"}, TTL = session_ttl_min
    demo:config                   the demo_config row, cached (written on every change)
    demo:data:v{N}:{city}         the generated dataset, no TTL
    demo:rate:{ip}:{hour}         sessions a visitor opened this hour

The settings row lives in PostgreSQL (migration 067) because an operator edits
it; a demo request reads only its Redis copy. The database is read once, when
the copy is missing (first request after a Redis flush).
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog

from app.services.demo.generator import DATA_VERSION, DEMO_CITIES, build, dumps

logger = structlog.get_logger()

SESSION_KEY = "demo:session:{}"
CONFIG_KEY = "demo:config"
DATA_KEY = "demo:data:v{version}:{city}"
RATE_KEY = "demo:rate:{ip}:{hour}"
SESSIONS_PER_IP_HOUR = 20
TABS = ("dashboard", "signals", "leads", "analytics")
DEFAULT_CONFIG = {"enabled": False, "demo_city": "Краснодар", "session_ttl_min": 30,
                  "headline": "Демо-режим REIP — данные синтетические", "allowed_tabs": list(TABS)}


def redis_client():
    import redis.asyncio as redis  # noqa: PLC0415

    from app.config import config  # noqa: PLC0415

    return redis.from_url(config.redis_url, socket_connect_timeout=2, socket_timeout=2,
                          decode_responses=True)


def _row_to_config(row) -> dict:
    if row is None:
        return dict(DEFAULT_CONFIG)
    return {"enabled": bool(row.enabled), "demo_city": row.demo_city,
            "session_ttl_min": int(row.session_ttl_min), "headline": row.headline,
            "allowed_tabs": [t for t in (row.allowed_tabs or []) if t in TABS] or list(TABS)}


async def load_config_from_db() -> dict:
    from app.database import async_session  # noqa: PLC0415
    from app.models.demo import DemoConfig  # noqa: PLC0415

    async with async_session() as session:
        return _row_to_config(await session.get(DemoConfig, 1))


async def get_config(redis) -> dict:
    raw = await redis.get(CONFIG_KEY)
    if raw:
        return {**DEFAULT_CONFIG, **json.loads(raw)}
    cfg = await load_config_from_db()
    await redis.set(CONFIG_KEY, json.dumps(cfg, ensure_ascii=False))
    return cfg


async def cache_config(redis, cfg: dict) -> None:
    await redis.set(CONFIG_KEY, json.dumps(cfg, ensure_ascii=False))


async def allow_new_session(redis, ip: Optional[str]) -> bool:
    key = RATE_KEY.format(ip=ip or "unknown", hour=int(time.time() // 3600))
    count = await redis.incr(key)
    await redis.expire(key, 3700)
    return count <= SESSIONS_PER_IP_HOUR


async def create_session(redis, cfg: dict, city: Optional[str] = None) -> dict:
    city = city if city in DEMO_CITIES else (cfg["demo_city"] if cfg["demo_city"] in DEMO_CITIES
                                             else DEMO_CITIES[0])
    token = uuid.uuid4().hex
    ttl = int(cfg["session_ttl_min"]) * 60
    now = datetime.now(timezone.utc)
    await redis.set(SESSION_KEY.format(token),
                    json.dumps({"city": city, "created_at": now.isoformat(), "role": "demo"},
                               ensure_ascii=False), ex=ttl)
    return {"token": token, "city": city, "expires_at": (now + timedelta(seconds=ttl)).isoformat()}


async def read_session(redis, token: str) -> Optional[dict]:
    if not token or len(token) > 64:
        return None
    raw = await redis.get(SESSION_KEY.format(token))
    return json.loads(raw) if raw else None


async def set_city(redis, token: str, city: str) -> Optional[dict]:
    key = SESSION_KEY.format(token)
    raw = await redis.get(key)
    if not raw or city not in DEMO_CITIES:
        return None
    sess = json.loads(raw)
    sess["city"] = city
    ttl = await redis.ttl(key)
    await redis.set(key, json.dumps(sess, ensure_ascii=False), ex=max(ttl, 60))
    return sess


async def get_data(redis, city: str) -> dict:
    key = DATA_KEY.format(version=DATA_VERSION, city=city)
    raw = await redis.get(key)
    if raw:
        return json.loads(raw)
    data = build(city)
    await redis.set(key, dumps(data))  # no TTL: invalidated by DATA_VERSION
    return data


async def save_config(session, operator_id: Optional[int], patch: dict) -> dict:
    """Validate and store a settings change, then refresh the Redis copy.
    Raises ValueError with a Russian message."""
    from app.models.demo import DemoConfig  # noqa: PLC0415

    row = await session.get(DemoConfig, 1)
    if row is None:
        row = DemoConfig(id=1, headline=DEFAULT_CONFIG["headline"],
                         allowed_tabs=list(TABS))
        session.add(row)
    for key, value in (patch or {}).items():
        if key == "enabled":
            row.enabled = bool(value)
        elif key == "demo_city":
            if value not in DEMO_CITIES:
                raise ValueError(f"город демо — один из: {', '.join(DEMO_CITIES)}")
            row.demo_city = value
        elif key == "session_ttl_min":
            if not isinstance(value, int) or not 5 <= value <= 1440:
                raise ValueError("длительность сессии — от 5 до 1440 минут")
            row.session_ttl_min = value
        elif key == "headline":
            text = " ".join(str(value or "").split())[:200]
            if not text:
                raise ValueError("заголовок не может быть пустым")
            row.headline = text
        elif key == "allowed_tabs":
            tabs = [t for t in TABS if t in set(value or [])]
            if not tabs or set(value or []) - set(TABS):
                raise ValueError(f"вкладки демо — из: {', '.join(TABS)}")
            row.allowed_tabs = tabs
        else:
            raise ValueError(f"неизвестный параметр: {key}")
    row.updated_by = operator_id
    await session.commit()
    cfg = _row_to_config(row)
    redis = redis_client()
    try:
        await cache_config(redis, cfg)
    finally:
        await redis.aclose()
    logger.info("Demo settings changed", operator=operator_id, enabled=cfg["enabled"])
    return cfg
