"""Health check endpoints. TZ section 6.3.

/api/health       - liveness (always ok)
/api/health/deep  - readiness: PostgreSQL + Redis (AI check added later)
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import config
from app.database import check_database_connection

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
    """Deep readiness probe: database + redis."""
    checks: dict[str, str] = {}

    try:
        checks["database"] = "ok" if await check_database_connection() else "error"
    except Exception as e:  # noqa: BLE001
        checks["database"] = f"error: {str(e)[:100]}"

    try:
        import redis.asyncio as redis

        client = redis.from_url(config.redis_url)
        await client.ping()
        await client.aclose()
        checks["redis"] = "ok"
    except Exception as e:  # noqa: BLE001
        checks["redis"] = f"error: {str(e)[:100]}"

    # AI provider check is added once ai_service is implemented.
    checks["ai"] = "not_configured"

    critical_ok = all(
        value == "ok" for key, value in checks.items() if key in ("database", "redis")
    )
    overall = "ok" if critical_ok else "degraded"
    return DeepHealthResponse(status=overall, checks=checks, timestamp=_now(), version=VERSION)
