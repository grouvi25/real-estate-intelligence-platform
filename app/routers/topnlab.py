"""TopNLab settings of an agency. ТЗ «Интеграция с TopNLab» v1.0, раздел 8.

Four fields (appkey, company id, virtual number, sync on/off) plus an optional
manager e-mail for auto-assignment, and three actions: check the connection,
register the «Аналитика REIP» report button, fetch the Avito keys. All of it is
owner-only: the connector decides where every lead goes.

Stored in the agency's agency_crm_config row with connector_type='topnlab' (see
app.services.topnlab_adapter). Saving here makes TopNLab the agency's CRM.
"""
from __future__ import annotations

import re
import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from app.config import config
from app.database import get_session
from app.dependencies import CurrentManager, get_current_manager, require_owner
from app.exceptions import AppException

logger = structlog.get_logger()
router = APIRouter()

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
AVITO_SITES = ("AVITO", "CIAN", "BANK", "YANDEX")


class TopnlabSettingsRequest(BaseModel):
    appkey: Optional[str] = None  # write-only; empty keeps the stored key
    company_id: Optional[str] = None
    virtual_number: Optional[str] = None
    manager_email: Optional[str] = None
    sync_enabled: Optional[bool] = None


async def _row(session, agency_id: uuid.UUID, *, create: bool = False):
    """The agency's CRM row: its TopNLab one if any, else the single row the
    agency settings screen edits (one CRM per agency), else a new one."""
    from app.models.agency_crm_config import AgencyCRMConfig  # noqa: PLC0415

    rows = (await session.execute(
        select(AgencyCRMConfig).where(AgencyCRMConfig.agency_id == agency_id)
    )).scalars().all()
    for row in rows:
        if row.crm_type == "topnlab":
            return row
    if not create:
        return None
    if rows:
        return rows[0]
    row = AgencyCRMConfig(agency_id=agency_id, crm_type="topnlab", config={})
    session.add(row)
    return row


def _dto(row) -> dict:
    from app.services.topnlab_adapter import report_webhook_url  # noqa: PLC0415

    active = row is not None and row.crm_type == "topnlab" and row.is_active
    extra = dict(row.config or {}) if active else {}
    token = extra.get("report_token")
    return {
        "active": active,
        "has_key": bool(active and row.api_key),
        "company_id": extra.get("company_id"),
        "virtual_number": extra.get("virtual_number"),
        "manager_email": extra.get("manager_email"),
        "sync_enabled": bool(extra.get("sync_enabled")),
        "report_menu_id": extra.get("report_menu_id"),
        "avito_credentials_saved": bool(extra.get("avito_credentials_encrypted")),
        "incoming_webhook_url": (
            f"{config.base_url.rstrip('/')}/api/topnlab/incoming-webhook?token={token}"
            if token else None),
        "report_webhook_url": report_webhook_url(token) if token else None,
        # Общий рубильник живёт в .env; владелец должен видеть, что без него
        # его галочка ничего не отправит.
        "globally_enabled": config.topnlab_sync_enabled,
        "min_score": config.topnlab_lead_min_score,
    }


@router.get("/settings")
async def get_settings(
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    await require_owner(session, current)
    return _dto(await _row(session, uuid.UUID(current.agency_id)))


@router.put("/settings")
async def save_settings(
    req: TopnlabSettingsRequest,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    await require_owner(session, current)
    row = await _row(session, uuid.UUID(current.agency_id), create=True)
    if row.crm_type != "topnlab":
        logger.info("Agency CRM switched to TopNLab", agency_id=current.agency_id,
                    previous=row.crm_type)
        row.crm_type = "topnlab"
        row.base_url = None  # the old CRM's address means nothing to TopNLab
        row.api_key = None
        row.config = {}
    row.is_active = True

    extra = dict(row.config or {})
    if req.appkey and req.appkey.strip():
        row.api_key = req.appkey.strip()
    if req.company_id is not None:
        company = req.company_id.strip()
        if company and not company.isdigit():
            raise AppException(400, "ID компании TopNLab — это число", "VALIDATION_ERROR")
        extra["company_id"] = company or None
    if req.virtual_number is not None:
        digits = "".join(ch for ch in req.virtual_number if ch.isdigit())
        if digits and len(digits) not in (10, 11):
            raise AppException(400, "Номер АТС — 10 цифр без +7", "VALIDATION_ERROR")
        extra["virtual_number"] = digits[-10:] if digits else None
    if req.manager_email is not None:
        email = req.manager_email.strip()
        if email and not EMAIL.match(email):
            raise AppException(400, "Похоже, в e-mail ошибка", "VALIDATION_ERROR")
        extra["manager_email"] = email or None
    if req.sync_enabled is not None:
        if req.sync_enabled and not row.api_key:
            raise AppException(400, "Сначала укажите ключ API TopNLab", "VALIDATION_ERROR")
        extra["sync_enabled"] = bool(req.sync_enabled)
    extra.setdefault("report_token", secrets.token_urlsafe(24))
    row.config = extra  # new dict: JSONB changes are only seen on assignment

    await session.commit()
    logger.info("TopNLab settings saved", agency_id=current.agency_id,
                sync_enabled=extra.get("sync_enabled"))
    return _dto(row)


async def _settings_or_400(session, current: CurrentManager):
    from app.services.topnlab_adapter import settings_from_config  # noqa: PLC0415

    await require_owner(session, current)
    row = await _row(session, uuid.UUID(current.agency_id))
    s = settings_from_config(row) if row is not None and row.is_active else None
    if s is None:
        raise AppException(400, "Сначала сохраните ключ API TopNLab", "TOPNLAB_NOT_CONFIGURED")
    return row, s


def _topnlab_error(e: Exception) -> AppException:
    from app.services.topnlab_adapter import TopnlabUnavailable  # noqa: PLC0415

    if isinstance(e, TopnlabUnavailable):
        return AppException(502, "TopNLab не отвечает, попробуйте позже", "TOPNLAB_UNAVAILABLE")
    return AppException(400, f"TopNLab отказал: {e}", "TOPNLAB_REJECTED")


@router.post("/check")
async def check(
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """«Проверить подключение»: the key is good if task types come back."""
    from app.services.topnlab_adapter import (  # noqa: PLC0415
        TopnlabError,
        find_call_task_type,
        get_topnlab_task_types,
    )

    _, s = await _settings_or_400(session, current)
    try:
        types = await get_topnlab_task_types(s, use_cache=False)
    except TopnlabError as e:
        raise _topnlab_error(e) from None
    call_type = find_call_task_type(types)
    return {
        "ok": True,
        "task_types": len(types),
        "call_task_type_id": call_type,
        "message": "Подключение работает" if call_type else
                   "Подключение работает, но в TopNLab нет типа задачи «Позвонить»",
    }


@router.post("/register-report")
async def register_report(
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """«Зарегистрировать отчёт REIP» in TopNLab's mass-action menu."""
    from app.services.topnlab_adapter import TopnlabError, register_reip_report  # noqa: PLC0415

    row, s = await _settings_or_400(session, current)
    try:
        menu_id, token, created = await register_reip_report(s)
    except TopnlabError as e:
        raise _topnlab_error(e) from None
    row.config = {**(row.config or {}), "report_menu_id": menu_id, "report_token": token}
    await session.commit()
    return {"ok": True, "report_menu_id": menu_id, "created": created,
            "message": f"Отчёт зарегистрирован. ID: {menu_id}" if created
            else f"Отчёт уже был зарегистрирован. ID: {menu_id}"}


@router.post("/avito-credentials")
async def fetch_avito_credentials(
    site: str = "AVITO",
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """«Получить ключи Avito»: stored encrypted, never shown back."""
    from app.services.topnlab_adapter import (  # noqa: PLC0415
        TopnlabError,
        encrypt_blob,
        get_avito_credentials,
    )

    site = site.upper()
    if site not in AVITO_SITES:
        raise AppException(400, f"Площадка: одна из {', '.join(AVITO_SITES)}", "VALIDATION_ERROR")
    row, s = await _settings_or_400(session, current)
    try:
        creds = await get_avito_credentials(s, site)
    except TopnlabError as e:
        raise _topnlab_error(e) from None
    if not creds:
        return {"ok": False, "message": f"В TopNLab нет ключей для {site}"}
    row.config = {
        **(row.config or {}),
        f"{site.lower()}_credentials_encrypted": encrypt_blob(creds),
        f"{site.lower()}_credentials_fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    await session.commit()
    return {"ok": True, "message": "Ключи получены и сохранены"}
