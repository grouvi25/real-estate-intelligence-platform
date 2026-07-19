"""Shared FastAPI dependencies (auth context)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Header

from app.exceptions import AppException
from app.security import TokenError, decode_access_token


@dataclass
class CurrentManager:
    manager_id: str
    agency_id: str


async def get_current_manager(authorization: Optional[str] = Header(default=None)) -> CurrentManager:
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

    return CurrentManager(manager_id=str(manager_id), agency_id=str(agency_id))
