"""Demo mode. ТЗ «Сигналы» v1.0, апгрейд C.

    GET   /api/demo/config     public: is the demo on, which cities (for a landing page)
    POST  /api/demo/session    public: open a demo session -> X-Demo-Token
    GET   /api/demo/settings   operator: the demo_config row
    PATCH /api/demo/settings   operator: change it (the one-toggle switch, D-08)

GET/PATCH /api/demo/session with the token are answered by the middleware.
"""
from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.config import config
from app.database import get_session
from app.dependencies import get_platform_operator
from app.exceptions import AppException

router = APIRouter()


def _cta_url() -> Optional[str]:
    """Where «Оставьте заявку» leads: the sales bot, else the landing page."""
    if config.platform_onboarding_bot_username:
        return f"https://t.me/{config.platform_onboarding_bot_username.lstrip('@')}"
    return config.platform_landing_url or None


@router.get("/config")
async def demo_public_config():
    from app.services.demo import session as demo  # noqa: PLC0415
    from app.services.demo.generator import DEMO_CITIES  # noqa: PLC0415

    redis = demo.redis_client()
    try:
        cfg = await demo.get_config(redis)
    finally:
        await redis.aclose()
    return {"enabled": cfg["enabled"], "cities": DEMO_CITIES, "default_city": cfg["demo_city"],
            "headline": cfg["headline"], "session_ttl_min": cfg["session_ttl_min"],
            "allowed_tabs": cfg["allowed_tabs"], "cta_url": _cta_url()}


class DemoSessionRequest(BaseModel):
    city: Optional[str] = None


@router.post("/session", status_code=201)
async def open_demo_session(req: DemoSessionRequest, request: Request):
    from app.services.demo import session as demo  # noqa: PLC0415
    from app.services.demo.generator import DEMO_CITIES  # noqa: PLC0415

    redis = demo.redis_client()
    try:
        cfg = await demo.get_config(redis)
        if not cfg["enabled"]:
            raise AppException(403, "Демо-режим сейчас выключен", "DEMO_DISABLED")
        ip = request.headers.get("x-real-ip") or (request.client.host if request.client else None)
        if not await demo.allow_new_session(redis, ip):
            raise AppException(429, "Слишком много демо-сессий, попробуйте через час", "DEMO_RATE")
        sess = await demo.create_session(redis, cfg, req.city)
        await demo.get_data(redis, sess["city"])  # warm the dataset before the first screen
    finally:
        await redis.aclose()
    return {**sess, "cities": DEMO_CITIES, "headline": cfg["headline"],
            "session_ttl_min": cfg["session_ttl_min"], "allowed_tabs": cfg["allowed_tabs"],
            "cta_url": _cta_url()}


@router.get("/settings")
async def demo_settings(operator_id: int = Depends(get_platform_operator)):
    from app.services.demo.session import load_config_from_db  # noqa: PLC0415

    return await load_config_from_db()


@router.patch("/settings")
async def update_demo_settings(
    patch: dict,
    operator_id: int = Depends(get_platform_operator),
    session=Depends(get_session),
):
    from app.services.demo.session import save_config  # noqa: PLC0415

    try:
        return await save_config(session, operator_id, patch)
    except ValueError as e:
        raise AppException(400, str(e), "VALIDATION_ERROR") from None


class DemoLeadRequest(BaseModel):
    city: str
    agency_name: str
    phone: str
    name: Optional[str] = None
    consent: bool = False


@router.post("/request", status_code=201)
async def leave_request(req: DemoLeadRequest, request: Request, session=Depends(get_session)):
    """«Оставьте заявку» / «Подключить для {город}» (ТЗ «Сигналы» 7.5): the same
    onboarding request the sales bot creates, without Telegram -- the operators
    are notified and call the phone."""
    from app.models.billing import OnboardingRequest  # noqa: PLC0415
    from app.services import sales_bot  # noqa: PLC0415
    from app.services.demo import session as demo  # noqa: PLC0415
    from app.services.onboarding import check_city_availability  # noqa: PLC0415

    if not req.consent:
        raise AppException(400, "Нужно согласие на обработку персональных данных", "CONSENT_REQUIRED")
    phone = sales_bot._phone(req.phone)
    if phone is None:
        raise AppException(400, "Телефон в формате +7 900 123-45-67", "VALIDATION_ERROR")
    agency_name = " ".join(req.agency_name.split())[:200]
    if len(agency_name) < 2 or len(req.city.strip()) < 2:
        raise AppException(400, "Укажите город и название агентства", "VALIDATION_ERROR")
    redis = demo.redis_client()
    try:
        ip = request.headers.get("x-real-ip") or (request.client.host if request.client else None)
        key = f"demo:request:{ip}:{int(time.time() // 3600)}"
        if await redis.incr(key) > 5:
            raise AppException(429, "Заявка уже отправлена — мы свяжемся с вами", "DEMO_RATE")
        await redis.expire(key, 3700)
    finally:
        await redis.aclose()
    check = await check_city_availability(session, req.city)
    if not check.available:
        raise AppException(409, f"Город {check.city} уже занят другим агентством", "CITY_TAKEN")
    row = OnboardingRequest(telegram_id=None, display_name=(req.name or "").strip()[:100] or None,
                            city_name=check.city, agency_name=agency_name, plan_id="start",
                            status="pending", source="demo")
    row.phone = phone
    session.add(row)
    await session.commit()
    rid = str(row.id)[:8]
    await sales_bot.notify_operators(
        f"Новая заявка на REIP — из демо\nАгентство: {agency_name}\nГород: {check.city}\n"
        f"Контакт: {row.display_name or '—'}, +{phone}\nTelegram нет — звонить.\n\n"
        f"/approve_{rid} — тариф и оплата\n/reject_{rid} — отклонить")
    return {"ok": True, "city": check.city,
            "message": "Заявка отправлена — мы позвоним в ближайшее время"}
