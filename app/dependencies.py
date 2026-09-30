"""Shared FastAPI dependencies (auth context)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Header, Request

from app.exceptions import AppException
from app.security import TokenError, decode_access_token


@dataclass
class CurrentManager:
    manager_id: str
    agency_id: str


async def get_current_manager(
    authorization: Optional[str] = Header(default=None),
    request: Request = None,  # type: ignore[assignment]  # FastAPI injects it
) -> CurrentManager:
    """Validate the Bearer JWT and return the manager/agency context.

    The agency is taken from the token (not client input), so all data access is
    scoped to the authenticated manager's agency.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AppException(status_code=401, detail="Требуется авторизация", code="UNAUTHORIZED")

    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = decode_access_token(token)
    except TokenError as e:
        raise AppException(status_code=401, detail="Недействительный токен", code="INVALID_TOKEN") from e

    manager_id = payload.get("sub")
    agency_id = payload.get("agency_id")
    if not manager_id or not agency_id:
        raise AppException(status_code=401, detail="Некорректные данные токена", code="INVALID_TOKEN")

    from app.database import async_session
    from app.models.manager import Manager
    import uuid

    from app.models.agency import Agency

    async with async_session() as session:
        manager = await session.get(Manager, uuid.UUID(str(manager_id)))
        agency = await session.get(Agency, manager.agency_id) if manager is not None else None
    if manager is None or not manager.is_active or str(manager.agency_id) != str(agency_id):
        raise AppException(status_code=401, detail="Доступ к кабинету отозван", code="USER_REVOKED")

    # ТЗ «SaaS-слой» 3.3: an unpaid agency reads during the grace period and is
    # blocked after it. Called without a request (tests, internal use) = no gate.
    if request is not None and agency is not None:
        from app.services.billing import gate_request

        gate_request(agency, request.method, request.url.path)

    return CurrentManager(manager_id=str(manager_id), agency_id=str(agency_id))


async def require_owner(session, current: CurrentManager) -> None:
    """Reject owner-only mutations even when the UI is bypassed."""
    import uuid
    from app.models.manager import Manager
    manager = await session.get(Manager, uuid.UUID(current.manager_id))
    if manager is None or str(manager.agency_id) != current.agency_id or manager.role != "owner":
        raise AppException(status_code=403, detail="Действие доступно только владельцу агентства", code="OWNER_REQUIRED")


OPERATOR_ROLE = "platform_operator"


async def is_platform_operator(telegram_id: int) -> bool:
    """PLATFORM_OPERATOR_IDS in .env, or an active row in platform_operators."""
    from app.config import config

    if telegram_id in config.operator_telegram_ids:
        return True
    from sqlalchemy import select

    from app.database import async_session
    from app.models.billing import PlatformOperator

    async with async_session() as session:
        return bool(await session.scalar(select(PlatformOperator.id).where(
            PlatformOperator.telegram_id == telegram_id, PlatformOperator.is_active.is_(True))))


async def get_platform_operator(authorization: Optional[str] = Header(default=None)) -> int:
    """ТЗ «SaaS-слой» 6.2: the platform operator, by a dedicated JWT.

    The token carries role=platform_operator and the operator's Telegram id; it
    has no agency, so it cannot pass as a manager's, and a manager's token has no
    role, so it cannot pass here. The id is re-checked on every call: removing an
    operator revokes their token without rotating the secret.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AppException(status_code=401, detail="Нужен токен оператора", code="UNAUTHORIZED")
    try:
        payload = decode_access_token(authorization.split(" ", 1)[1].strip())
    except TokenError as e:
        raise AppException(status_code=401, detail="Недействительный токен", code="INVALID_TOKEN") from e
    sub = str(payload.get("sub", ""))
    if payload.get("role") != OPERATOR_ROLE or not sub.isdigit():
        raise AppException(status_code=403, detail="Только для оператора платформы", code="OPERATOR_ONLY")
    telegram_id = int(sub)
    if not await is_platform_operator(telegram_id):
        raise AppException(status_code=403, detail="Оператор отключён", code="OPERATOR_REVOKED")
    return telegram_id


def create_operator_token(telegram_id: int, days: int = 30) -> str:
    from datetime import timedelta

    from app.security import create_access_token

    return create_access_token(str(telegram_id), extra_claims={"role": OPERATOR_ROLE},
                               expires_delta=timedelta(days=days))
