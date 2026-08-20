"""Health check endpoints. TZ section 6.3.

/api/health       - liveness (always ok)
/api/health/deep  - readiness: PostgreSQL + Redis (AI check added later)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config import config
from app.database import check_database_connection, get_session

import structlog

logger = structlog.get_logger()
router = APIRouter()

VERSION = "2.0.0"


class HealthResponse(BaseModel):
    status: str
    timestamp: str
    version: str


class DeepHealthResponse(BaseModel):
    status: str
    checks: dict[str, str]
    timestamp: str
    version: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _telegram_dc_reachable(timeout: float = 4.0) -> bool:
    """Открывается ли TCP до дата-центра Telegram тем же путём, что у сбора.

    Сбор ходит по MTProto, а не в api.telegram.org, и адреса у них разные:
    бот может отвечать, пока дата-центры закрыты. Через прокси проверяем
    прокси, без него — прямое подключение.
    """
    from app.collectors.telegram_collector import _proxy_settings  # noqa: PLC0415

    host, port = "149.154.167.51", 443  # DC2, основной для наших сессий
    proxy = _proxy_settings()

    async def probe() -> bool:
        if proxy is None:
            _, writer = await asyncio.open_connection(host, port)
            writer.close()
            return True
        _, p_host, p_port = proxy
        reader, writer = await asyncio.open_connection(p_host, p_port)
        try:
            writer.write(b"\x05\x01\x00")
            await writer.drain()
            if await reader.readexactly(2) != b"\x05\x00":
                return False
            writer.write(b"\x05\x01\x00\x01"
                         + bytes(int(o) for o in host.split("."))
                         + port.to_bytes(2, "big"))
            await writer.drain()
            return (await reader.readexactly(10))[1] == 0
        finally:
            writer.close()

    try:
        # Предел на всю проверку, а не только на подключение: подвисший канал
        # принимает соединение и молчит, а чтение ответа без предела вешало
        # весь /health/deep — он переставал отвечать вообще.
        return await asyncio.wait_for(probe(), timeout=timeout)
    except Exception as e:  # noqa: BLE001 - проверка не должна ронять сам ответ
        # Молчаливый False уже однажды скрыл от нас, что сбор не работает.
        logger.warning("Telegram DC probe failed", error=f"{type(e).__name__}: {e}")
        return False


@router.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check() -> HealthResponse:
    """Basic liveness probe."""
    return HealthResponse(status="ok", timestamp=_now(), version=VERSION)


@router.get("/health/deep", response_model=DeepHealthResponse, tags=["Health"])
async def deep_health_check() -> DeepHealthResponse:
    """Deep readiness probe: database + redis. Bounded by short timeouts so the
    probe stays fast even when a dependency is down."""
    checks: dict[str, str] = {}

    try:
        db_ok = await asyncio.wait_for(check_database_connection(), timeout=3)
        checks["database"] = "ok" if db_ok else "error"
    except Exception as e:  # noqa: BLE001
        checks["database"] = f"error: {str(e)[:100]}"

    try:
        import redis.asyncio as redis

        client = redis.from_url(config.redis_url, socket_connect_timeout=2, socket_timeout=2)
        await asyncio.wait_for(client.ping(), timeout=3)
        await client.aclose()
        checks["redis"] = "ok"
    except Exception as e:  # noqa: BLE001
        checks["redis"] = f"error: {str(e)[:100]}"

    # AI provider readiness (does the selected provider have credentials).
    try:
        from app.services.ai_service import AIService

        ai = AIService()
        checks["ai"] = "configured" if ai.provider_configured else "not_configured"
        await ai.close()
    except Exception as e:  # noqa: BLE001
        checks["ai"] = f"error: {str(e)[:100]}"

    # Telegram bot reachability (non-critical). getMe is bounded so a slow or
    # blocked network never stalls the probe. A dummy/dev token reports an error
    # rather than failing readiness.
    try:
        token = config.telegram_bot_token
        if not token or token.startswith("dummy") or token == "changeme":
            checks["telegram_bot"] = "not_configured"
        else:
            import httpx

            # Через прокси (см. config.telegram_proxy_url) — из Yandex Cloud
            # Telegram напрямую недоступен. Проверка ходит по той же дороге,
            # что и боевые вызовы, иначе она врала бы про доступность.
            #
            # Внешний предел обязателен: через SOCKS собственный таймаут httpx
            # не срабатывает — подвисший канал держал запрос семь минут, и
            # /health/deep переставал отвечать целиком.
            async def _get_me():
                async with httpx.AsyncClient(timeout=5, proxy=config.telegram_proxy_url) as client:
                    return await client.get(f"https://api.telegram.org/bot{token}/getMe")

            resp = await asyncio.wait_for(_get_me(), timeout=8)
            checks["telegram_bot"] = "ok" if resp.status_code == 200 else f"error: {resp.status_code}"
    except Exception as e:  # noqa: BLE001
        checks["telegram_bot"] = f"error: {str(e)[:100]}"

    # Celery queue depth via the Redis broker (non-critical). Reports the pending
    # task backlog on the default queue so operators can spot a stuck worker.
    try:
        import redis.asyncio as redis

        client = redis.from_url(config.redis_url, socket_connect_timeout=2, socket_timeout=2)
        depth = await asyncio.wait_for(client.llen("celery"), timeout=3)
        await client.aclose()
        checks["celery_queue"] = f"ok: {int(depth)} pending"
    except Exception as e:  # noqa: BLE001
        checks["celery_queue"] = f"error: {str(e)[:100]}"

    # Telethon auth failures are intentionally paused to avoid a retry storm.
    try:
        if not config.telethon_api_id:
            checks["telethon"] = "not_configured"
        else:
            import redis.asyncio as redis

            client = redis.from_url(
                config.redis_url, socket_connect_timeout=2, socket_timeout=2)
            paused = await asyncio.wait_for(
                client.get("telethon:paused_until"), timeout=2)
            await client.aclose()
            if paused:
                checks["telethon"] = "paused (auth error)"
            else:
                # Сколько аккаунтов в запасе — такой же признак здоровья, как и
                # сама связь: сбор может идти на последнем живом, и узнать об
                # этом лучше заранее, а не когда он тоже выбыл.
                from app.collectors import telethon_sessions  # noqa: PLC0415

                alive = await telethon_sessions.alive_sessions()
                checks["telethon_accounts"] = f"{len(alive)} из {len(telethon_sessions.sessions())}"
                # Раньше здесь стояло просто "active" — по факту это значило
                # "ключи прописаны и пауза не выставлена". Проверка держалась
                # зелёной, пока из Yandex Cloud вообще не было связи с
                # дата-центрами Telegram, и сбор молча стоял. Теперь пробуем
                # дотянуться до дата-центра тем же путём, каким ходит сбор.
                checks["telethon"] = "active" if await _telegram_dc_reachable() else "unreachable"
    except Exception as e:  # noqa: BLE001
        checks["telethon"] = f"error: {str(e)[:50]}"

    critical_ok = all(
        value == "ok" for key, value in checks.items() if key in ("database", "redis")
    )
    overall = "ok" if critical_ok else "degraded"
    return DeepHealthResponse(status=overall, checks=checks, timestamp=_now(), version=VERSION)


class ReadinessResponse(BaseModel):
    ready: bool
    blockers: int
    warnings: int
    findings: dict[str, dict]
    timestamp: str
    version: str


@router.get("/health/readiness", response_model=ReadinessResponse, tags=["Health"])
async def readiness_check(session=Depends(get_session)) -> ReadinessResponse:
    """Go-live readiness: TZ 26 / 35.12.

    /health/deep answers "are the dependencies up". This answers the question
    that actually matters -- if a buyer appeared right now, could the agency act
    on them? A system with an empty catalogue, no live sources or a bot token
    that was never set is green on /health/deep and useless in practice.

    Manager-scoped is unnecessary: it reports configuration state and counts, no
    personal data, and the operator needs it before anyone can log in.
    """
    from app.services.readiness import readiness_report

    report = await readiness_report(session)
    return ReadinessResponse(**report, timestamp=_now(), version=VERSION)
