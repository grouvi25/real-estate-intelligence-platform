"""Health check endpoints. TZ section 6.3.

/api/health       - liveness (always ok)
/api/health/deep  - readiness: PostgreSQL + Redis (AI check added later)
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config import config
from app.database import check_database_connection, get_session

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


@router.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check() -> HealthResponse:
    """Basic liveness probe."""
    return HealthResponse(status="ok", timestamp=_now(), version=VERSION)


@router.get("/health/deep", response_model=DeepHealthResponse, tags=["Health"])
async def deep_health_check() -> DeepHealthResponse:
    """Deep readiness probe: database + redis. Bounded by short timeouts so the
    probe stays fast even when a dependency is down."""
    import asyncio

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

            async with httpx.AsyncClient(timeout=3) as client:
                resp = await client.get(f"https://api.telegram.org/bot{token}/getMe")
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
            checks["telethon"] = "paused (auth error)" if paused else "active"
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
