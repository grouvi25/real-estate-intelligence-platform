"""Security helpers: JWT creation and verification. TZ sections 3.2 / 13.1.

Managers authenticate via Telegram/MAX initData (see routers/auth.py); after a
successful handshake the backend issues a signed JWT used for all API calls.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import jwt

from app.config import config

ALGORITHM = "HS256"
DEFAULT_EXPIRY_DAYS = 7


class TokenError(Exception):
    """Raised when a JWT is invalid, expired, or tampered with."""


def create_access_token(
    subject: str,
    agency_id: Optional[str] = None,
    extra_claims: Optional[dict[str, Any]] = None,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a signed JWT for the given manager id (subject)."""
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(days=DEFAULT_EXPIRY_DAYS))
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": now,
        "exp": expire,
    }
    if agency_id is not None:
        payload["agency_id"] = agency_id
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, config.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT. Raises TokenError on any problem."""
    try:
        return jwt.decode(token, config.secret_key, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as e:
        raise TokenError("Token expired") from e
    except jwt.InvalidTokenError as e:
        raise TokenError("Invalid token") from e
