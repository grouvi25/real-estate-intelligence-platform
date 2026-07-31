"""Unified platform auth (Telegram + MAX). TZ section 13.1.

Both platforms use the same construction; see verify_max_init_data for the one
difference (MAX signs URL-decoded values).

Security fix vs. the illustrative TZ: Telegram Mini App (WebApp) initData must be
verified with the WebApp algorithm:

    secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)
    expected   = HMAC_SHA256(key=secret_key,   msg=data_check_string)

The TZ used sha256(bot_token) which is the legacy Login Widget scheme and is
invalid for WebApp initData.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Optional
from urllib.parse import parse_qsl, unquote

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import config
from app.database import get_session
from app.exceptions import AppException
from app.models.manager import Manager
from app.security import create_access_token
from app.services.bot_abstraction import BotPlatform

logger = structlog.get_logger()
router = APIRouter()

INIT_DATA_MAX_AGE_SECONDS = 24 * 60 * 60


class AuthRequest(BaseModel):
    platform: str = Field(..., pattern="^(telegram|max)$")
    init_data: str


def verify_telegram_init_data(init_data: str) -> Optional[dict]:
    """Validate a Telegram WebApp initData string. Returns the user dict or None."""
    pairs = dict(parse_qsl(init_data, strict_parsing=False))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        return None

    data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret_key = hmac.new(b"WebAppData", config.telegram_bot_token.encode(), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash):
        return None

    # Replay protection.
    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError:
        return None
    if time.time() - auth_date > INIT_DATA_MAX_AGE_SECONDS:
        return None

    try:
        return json.loads(pairs.get("user", "{}"))
    except json.JSONDecodeError:
        return None


def verify_max_init_data(init_data: str) -> Optional[dict]:
    """Validate MAX Mini App initData. https://dev.max.ru/docs/webapps/validation

    Same construction as Telegram -- secret_key = HMAC_SHA256("WebAppData",
    bot_token), then HMAC_SHA256(secret_key, sorted launch params) -- with one
    difference that matters: MAX signs the *decoded* values, so each value is
    unquoted before the check string is assembled. Telegram signs what arrives.

    Until this landed, production rejected every MAX login outright rather than
    fall back to trusting unsigned initData, which would have let anyone sign in
    as any manager of any agency.
    """
    if not init_data or not config.max_bot_token:
        return None
    try:
        pairs = [p.split("=", 1) for p in init_data.split("&") if "=" in p]
        hashes = [v for k, v in pairs if k == "hash"]
        if len(hashes) != 1:
            return None
        received_hash = hashes[0]

        decoded = [(k, unquote(v)) for k, v in pairs]

        auth_date = next((v for k, v in decoded if k == "auth_date"), None)
        if auth_date is not None:
            if time.time() - int(auth_date) > INIT_DATA_MAX_AGE_SECONDS:
                return None

        launch_params = "\n".join(
            f"{k}={v}" for k, v in sorted(((k, v) for k, v in decoded if k != "hash"),
                                          key=lambda kv: kv[0])
        )
        secret_key = hmac.new(b"WebAppData", config.max_bot_token.encode(), hashlib.sha256).digest()
        expected = hmac.new(secret_key, launch_params.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, received_hash):
            return None

        user_raw = next((v for k, v in decoded if k == "user"), None)
        return json.loads(user_raw) if user_raw else None
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


@router.post("/platform")
async def auth_platform(req: AuthRequest, session=Depends(get_session)):
    """Verify platform initData, upsert the manager, and issue a JWT."""
    user = (
        verify_telegram_init_data(req.init_data)
        if req.platform == "telegram"
        else verify_max_init_data(req.init_data)
    )
    if not user or user.get("id") is None:
        raise HTTPException(status_code=401, detail="Invalid platform signature")

    platform = BotPlatform(req.platform)
    platform_user_id = int(user["id"])

    if platform == BotPlatform.TELEGRAM:
        stmt = select(Manager).where(Manager.telegram_id == platform_user_id)
    else:
        stmt = select(Manager).where(Manager.max_user_id == platform_user_id)
    manager = (await session.execute(stmt)).scalar_one_or_none()

    if manager is None:
        # New manager: attach to the platform owner agency. Real onboarding
        # (linking to an arbitrary agency) is handled elsewhere.
        if not config.platform_owner_agency_id:
            raise AppException(
                status_code=409,
                detail="Онбординг не настроен: задайте PLATFORM_OWNER_AGENCY_ID",
                code="ONBOARDING_REQUIRED",
            )
        manager = Manager(
            agency_id=config.platform_owner_agency_id,
            name=user.get("first_name", "Unknown"),
            telegram_id=platform_user_id if platform == BotPlatform.TELEGRAM else None,
            max_user_id=platform_user_id if platform == BotPlatform.MAX else None,
            preferred_platform=req.platform,
            role="manager",
            is_active=True,
        )
        session.add(manager)
        await session.commit()
        await session.refresh(manager)

    token = create_access_token(str(manager.id), agency_id=str(manager.agency_id))
    return {
        "token": token,
        "manager": {
            "id": str(manager.id),
            "role": manager.role,
            "agency_id": str(manager.agency_id),
        },
    }
