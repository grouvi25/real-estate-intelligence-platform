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
import secrets
import time
import uuid
from typing import Optional
from urllib.parse import parse_qsl, unquote

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, text

from app.config import config
from app.database import get_session
from app.dependencies import CurrentManager, get_current_manager
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
    # The agency's invite token, carried by the owner's deeplink. Required for
    # anyone who is not already a manager.
    invite: Optional[str] = None


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


INVITE_PREFIX = "inv_"


async def _agency_for_invite(session, invite: Optional[str]) -> uuid.UUID:
    """Which agency an invite token admits to. Refuses anything else.

    The token is the whole of the authorisation, so it is compared against the
    stored one rather than parsed: a rotated token stops working immediately, and
    a missing or wrong one is refused rather than quietly falling back to the
    platform owner's agency.
    """
    from app.models.agency import Agency  # noqa: PLC0415

    token = (invite or "").strip()
    if token.startswith(INVITE_PREFIX):
        token = token[len(INVITE_PREFIX):]
    if not token:
        raise AppException(
            status_code=403,
            detail="Нужна ссылка-приглашение от владельца агентства",
            code="INVITE_REQUIRED",
        )

    agency_id = await session.scalar(
        select(Agency.id).where((Agency.invite_token == token) | (Agency.onboarding_code == token))
    )
    if agency_id is None:
        raise AppException(
            status_code=403,
            detail="Ссылка-приглашение недействительна или устарела",
            code="INVITE_INVALID",
        )
    return agency_id


async def _claim_owner_slot(session) -> bool:
    """Занять одно место в окне саморегистрации владельцев. TZ 13.

    Одним запросом: уменьшить счётчик, если он больше нуля, и сказать, вышло ли.
    Так два одновременных входа не займут одно место — а «только двое» здесь
    требование заказчика, не пожелание. Ноль мест или отсутствие таблицы
    (старая схема) означают закрытое окно, а не ошибку входа.
    """
    try:
        res = await session.execute(text(
            "UPDATE platform_claim SET remaining = remaining - 1, updated_at = now() "
            "WHERE remaining > 0 RETURNING remaining"
        ))
        return res.first() is not None
    except Exception as e:  # noqa: BLE001
        logger.warning("Окно саморегистрации недоступно", error=str(e)[:120])
        return False


@router.post("/platform")
async def auth_platform(req: AuthRequest, session=Depends(get_session)):
    """Verify platform initData, upsert the manager, and issue a JWT."""
    user = (
        verify_telegram_init_data(req.init_data)
        if req.platform == "telegram"
        else verify_max_init_data(req.init_data)
    )
    if not user or user.get("id") is None:
        # Refusals are logged with their reason because the only record we had
        # of a manager being turned away was a status code in the access log,
        # and 401 and 403 there mean two completely different conversations.
        logger.warning("Вход отклонён: подпись платформы не сошлась",
                       platform=req.platform, init_data_len=len(req.init_data or ""))
        raise HTTPException(status_code=401, detail="Invalid platform signature")

    platform = BotPlatform(req.platform)
    platform_user_id = int(user["id"])

    if platform == BotPlatform.TELEGRAM:
        stmt = select(Manager).where(Manager.telegram_id == platform_user_id)
    else:
        stmt = select(Manager).where(Manager.max_user_id == platform_user_id)
    manager = (await session.execute(stmt)).scalar_one_or_none()

    # The name is only ever set once, at the moment a manager first signs in --
    # so a row created any other way (an owner added by hand before their first
    # visit) kept whatever placeholder it was given, forever, on every screen
    # that names a person. Nothing in the product lets anyone edit it either, so
    # Telegram is the only source of truth there is; keep it in step.
    if manager is not None:
        first_name = (user.get("first_name") or "").strip()
        if first_name and manager.name != first_name:
            manager.name = first_name
            await session.commit()

    if manager is None:
        # ADMIN_TELEGRAM_ID is the one trusted bootstrap identity. After a full
        # user reset it must be able to recreate the platform owner without an
        # invite; everybody else remains invite-only. MAX_ADMIN_IDS is the same
        # thing for MAX, where identities are known in advance.
        is_platform_admin = bool(
            config.platform_owner_agency_id
            and (
                (platform == BotPlatform.TELEGRAM
                 and config.admin_telegram_id is not None
                 and platform_user_id == int(config.admin_telegram_id))
                or (platform == BotPlatform.MAX
                    and platform_user_id in config.max_admin_ids)
            )
        )
        # Окно саморегистрации: у людей, которых надо впустить, идентификатор в
        # MAX заранее неизвестен — MAX показывает его только при первом входе.
        # Поэтому следующие несколько незнакомцев из MAX становятся владельцами
        # сами, а счётчик в базе закрывает окно навсегда. Только MAX: в Telegram
        # вход по-прежнему строго по приглашению.
        claimed_slot = False
        if not is_platform_admin and platform == BotPlatform.MAX and config.platform_owner_agency_id:
            claimed_slot = await _claim_owner_slot(session)

        if is_platform_admin or claimed_slot:
            agency_id = uuid.UUID(str(config.platform_owner_agency_id))
            role = "owner"
            if claimed_slot:
                logger.warning(
                    "Владелец создан по окну саморегистрации MAX",
                    platform_user_id=platform_user_id,
                    name=user.get("first_name"),
                )
        else:
            try:
                agency_id = await _agency_for_invite(session, req.invite)
            except AppException as e:
                logger.warning("Вход отклонён: приглашение не принято",
                    platform=req.platform, platform_user_id=platform_user_id,
                    has_invite=bool(req.invite), code=e.code)
                raise
        manager = Manager(
            agency_id=agency_id,
            name=user.get("first_name", "Unknown"),
            telegram_id=platform_user_id if platform == BotPlatform.TELEGRAM else None,
            max_user_id=platform_user_id if platform == BotPlatform.MAX else None,
            preferred_platform=req.platform,
            role=role if (is_platform_admin or claimed_slot) else "manager",
            is_active=True,
        )
        session.add(manager)
        await session.commit()
        await session.refresh(manager)

    token = create_access_token(str(manager.id), agency_id=str(manager.agency_id))
    from app.models.agency import Agency  # noqa: PLC0415

    agency = await session.get(Agency, manager.agency_id)
    return {
        "token": token,
        "manager": {
            "id": str(manager.id),
            "name": manager.name,
            "role": manager.role,
            "agency_id": str(manager.agency_id),
        },
        # Public front-end settings travel with the handshake rather than in
        # their own endpoint: the Mini App already stores this response, and a
        # domain-restricted maps key is not a secret.
        "maps_key": config.yandex_maps_api_key,
        # The cabinet has to name the agency to a human; a UUID is not a name.
        "agency": {
            "id": str(manager.agency_id),
            "name": agency.name if agency else None,
            "city": agency.base_city if agency else None,
        },
    }


class InviteResponse(BaseModel):
    link: str
    token: str


async def _owner(current: CurrentManager, session) -> Manager:
    """The manager, if they may hand out invitations."""
    manager = await session.get(Manager, uuid.UUID(current.manager_id))
    if manager is None or manager.role != "owner":
        raise AppException(status_code=403, detail="Только для владельца агентства",
                           code="OWNER_ONLY")
    return manager


def invite_link(token: str) -> str:
    return f"https://t.me/{config.telegram_bot_username}?start={INVITE_PREFIX}{token}"


@router.get("/invite", response_model=InviteResponse)
async def get_invite(
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """The link that adds a manager to this agency."""
    from app.models.agency import Agency

    await _owner(current, session)
    agency = await session.get(Agency, uuid.UUID(current.agency_id))
    if not agency.invite_token:
        agency.invite_token = secrets.token_hex(16)
        await session.commit()
    return InviteResponse(link=invite_link(agency.invite_token), token=agency.invite_token)


@router.post("/invite/rotate", response_model=InviteResponse)
async def rotate_invite(
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """Issue a new link and kill the old one.

    The one thing to do when a link has gone somewhere it should not have.
    """
    from app.models.agency import Agency

    await _owner(current, session)
    agency = await session.get(Agency, uuid.UUID(current.agency_id))
    agency.invite_token = secrets.token_hex(16)
    await session.commit()
    logger.info("Invite rotated", agency_id=current.agency_id)
    return InviteResponse(link=invite_link(agency.invite_token), token=agency.invite_token)


class AiProviderResponse(BaseModel):
    provider: str
    configured: bool
    source: str  # "admin" — выбран владельцем, "env" — из настроек сервера
    options: list[dict]


class AiProviderRequest(BaseModel):
    provider: str


async def _provider_state(chosen: Optional[str]) -> AiProviderResponse:
    from app.services.ai_service import AIProvider, AIService

    service = AIService()
    try:
        current = await service.resolve_provider()
        options = []
        for p in AIProvider:
            service.provider = p
            options.append({
                "value": p.value,
                "configured": service.provider_configured,
                # The one thing an owner has to know when choosing: where the
                # data goes. 152-ФЗ, not a preference.
                "data_stays_in_russia": p in (AIProvider.YANDEX_GPT, AIProvider.GIGACHAT),
            })
        service.provider = current
        return AiProviderResponse(
            provider=current.value,
            configured=service.provider_configured,
            source="admin" if chosen else "env",
            options=options,
        )
    finally:
        await service.http.aclose()


@router.get("/ai-provider", response_model=AiProviderResponse)
async def get_ai_provider(
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    from app.services.platform_settings import AI_PROVIDER, get_setting

    await _owner(current, session)
    return await _provider_state(await get_setting(AI_PROVIDER))


@router.put("/ai-provider", response_model=AiProviderResponse)
async def set_ai_provider(
    req: AiProviderRequest,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """Switch the provider. Applies to the next AI call, no restart (TZ 2.2)."""
    from app.services.ai_service import AIProvider
    from app.services.platform_settings import AI_PROVIDER, set_setting

    await _owner(current, session)
    try:
        provider = AIProvider(req.provider)
    except ValueError:
        raise AppException(status_code=400, detail=f"Неизвестный провайдер: {req.provider}",
                           code="UNKNOWN_PROVIDER") from None

    await set_setting(AI_PROVIDER, provider.value, updated_by=current.manager_id)
    return await _provider_state(provider.value)


class AgencyResponse(BaseModel):
    id: str
    name: str
    city: str
    crm: Optional[dict] = None


class AgencyUpdateRequest(BaseModel):
    name: Optional[str] = None
    city: Optional[str] = None
    crm_type: Optional[str] = None
    crm_base_url: Optional[str] = None
    crm_api_key: Optional[str] = None


def _agency_dto(agency, crm=None) -> AgencyResponse:
    return AgencyResponse(
        id=str(agency.id), name=agency.name, city=agency.base_city,
        crm={"type": crm.crm_type, "base_url": crm.base_url,
             "has_key": bool(crm.api_key), "is_active": crm.is_active} if crm else None,
    )


async def _agency_crm(session, agency_id):
    from sqlalchemy import select as _select

    from app.models.agency_crm_config import AgencyCRMConfig

    return (await session.execute(
        _select(AgencyCRMConfig).where(AgencyCRMConfig.agency_id == agency_id).limit(1)
    )).scalars().first()


@router.get("/config")
async def public_config(
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """Non-secret front-end settings and the current manager's UI role."""
    manager = await session.get(Manager, uuid.UUID(current.manager_id))
    return {
        "maps_key": config.yandex_maps_api_key,
        "manager": {
            "id": current.manager_id,
            "role": manager.role if manager else "manager",
            "name": manager.name if manager else None,
        },
    }


@router.get("/agency", response_model=AgencyResponse)
async def get_agency(
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """The agency's own record. Editing it used to mean an UPDATE by hand."""
    from app.models.agency import Agency

    agency = await session.get(Agency, uuid.UUID(current.agency_id))
    if agency is None:
        raise AppException(status_code=404, detail="Агентство не найдено", code="NOT_FOUND")
    return _agency_dto(agency, await _agency_crm(session, agency.id))


@router.patch("/agency", response_model=AgencyResponse)
async def update_agency(
    req: AgencyUpdateRequest,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """Rename the agency, move its base city, choose which CRM to export to.

    The CRM connector decides where every qualified lead goes, so it belongs to
    the owner and not to anyone with a login.
    """
    from app.models.agency import Agency
    from app.models.agency_crm_config import AgencyCRMConfig
    from app.services.crm import SUPPORTED_CRMS

    await _owner(current, session)
    agency = await session.get(Agency, uuid.UUID(current.agency_id))
    if agency is None:
        raise AppException(status_code=404, detail="Агентство не найдено", code="NOT_FOUND")

    if req.name is not None:
        if not req.name.strip():
            raise AppException(status_code=400, detail="Название не может быть пустым",
                               code="VALIDATION_ERROR")
        agency.name = req.name.strip()
    if req.city is not None and req.city.strip():
        agency.base_city = req.city.strip()

    crm = await _agency_crm(session, agency.id)
    if req.crm_type is not None:
        if req.crm_type and req.crm_type not in SUPPORTED_CRMS:
            raise AppException(
                status_code=400,
                detail=f"Неизвестная CRM: {req.crm_type}. Доступны: {', '.join(SUPPORTED_CRMS)}",
                code="UNKNOWN_CRM")
        if not req.crm_type:
            # Empty means "back to the generic webhook", which is the fallback.
            if crm is not None:
                crm.is_active = False
        else:
            if crm is None:
                crm = AgencyCRMConfig(agency_id=agency.id, crm_type=req.crm_type)
                session.add(crm)
            crm.crm_type = req.crm_type
            crm.is_active = True
    if crm is not None:
        if req.crm_base_url is not None:
            crm.base_url = req.crm_base_url.strip() or None
        if req.crm_api_key:
            crm.api_key = req.crm_api_key  # encrypted by the model

    await session.commit()
    logger.info("Agency updated", agency_id=str(agency.id))
    return _agency_dto(agency, crm if crm and crm.is_active else None)
