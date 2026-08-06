"""Production-readiness checks. TZ 26 / 35.12 (go-live checklist).

Everything here is a configuration or data condition that leaves the system
running but not actually able to do its job. Each one was found by inspecting the
live deployment and then written down in a chat message -- which is exactly the
wrong place for it, because the next person to look has no way to know.

The checks answer one question: if a buyer appeared right now, would the agency
be able to act on them? A green /health/deep does not mean yes -- the database
can be up, Redis up, the AI configured, and the system still has nothing to offer
a lead and no safe way to notify anyone.

Severity is either "blocker" (the core scenario cannot complete) or "warning"
(it works, with a real risk or a degraded path).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import structlog

from app.config import config

logger = structlog.get_logger()

SEED_CATALOGUE_MAX = 5

# Values that ship in .env.example and mean "not configured yet".
PLACEHOLDERS = ("dev", "dummy", "test", "changeme", "todo", "xxx", "your", "placeholder", "")


def _is_placeholder(value: Optional[str]) -> bool:
    if not value:
        return True
    lowered = str(value).strip().lower()
    return lowered in PLACEHOLDERS or any(lowered.startswith(p) for p in PLACEHOLDERS if p)


@dataclass
class Finding:
    key: str
    severity: str  # "blocker" | "warning"
    detail: str
    action: str

    def as_dict(self) -> dict:
        return {"severity": self.severity, "detail": self.detail, "action": self.action}


async def collect_findings(session, agency_id: Optional[str] = None) -> list[Finding]:
    """Inspect configuration and data; return everything standing in the way.

    Data checks are scoped to one agency -- the platform owner by default. The
    system is multi-tenant (TZ 1.3 level 2), so counting across every agency
    would let a well-stocked tenant hide an empty one.
    """
    import uuid as _uuid

    from sqlalchemy import func, select

    from app.models.property import Property
    from app.models.source import Source

    findings: list[Finding] = []
    agency_id = agency_id or config.platform_owner_agency_id
    scope = None
    if agency_id:
        try:
            scope = _uuid.UUID(str(agency_id))
        except (ValueError, AttributeError, TypeError):
            logger.warning("Readiness: unusable agency id", agency_id=str(agency_id))

    def _scoped(stmt, column):
        return stmt.where(column == scope) if scope else stmt

    # --- can we offer anything to a buyer at all? ---------------------------
    active_properties = await session.scalar(
        _scoped(select(func.count()).select_from(Property).where(Property.status == "active"),
                Property.agency_id)
    ) or 0
    if active_properties == 0:
        findings.append(Finding(
            "catalogue", "blocker",
            "В каталоге нет активных объектов",
            "Загрузите каталог: Объекты → «Загрузить каталог» (CSV или XLSX)",
        ))
    elif active_properties < SEED_CATALOGUE_MAX:
        # There is no flag distinguishing seeded rows from imported ones, so the
        # count is the honest signal: production sat on two demo objects while
        # the check would have called that a catalogue. Said as a suspicion, not
        # a fact.
        findings.append(Finding(
            "catalogue_size", "warning",
            f"В каталоге всего {active_properties} объект(а) — похоже на тестовые данные",
            "Загрузите настоящий каталог агентства, иначе подбор нечего предложить лиду",
        ))

    # --- is anything feeding the pipeline? ----------------------------------
    live_sources = await session.scalar(
        _scoped(select(func.count()).select_from(Source)
                .where(Source.status.in_(("active", "sandbox"))), Source.agency_id)
    ) or 0
    if live_sources == 0:
        findings.append(Finding(
            "sources", "blocker",
            "Нет источников в работе — сигналам неоткуда взяться",
            "Дождитесь еженедельного поиска или добавьте чат вручную на экране «Источники»",
        ))

    if not (config.telethon_api_id and config.telethon_api_hash):
        findings.append(Finding(
            "collector", "blocker",
            "Telethon не настроен — коллектор не читает чаты",
            "Задайте TELETHON_API_ID и TELETHON_API_HASH, затем выполните вход",
        ))

    # --- single point of failure on one Telegram account --------------------
    # The collector reads public chats as a userbot, which Telegram may limit or
    # ban. If that is also the admin account, one ban takes out data collection
    # and the notification channel at the same time.
    if config.telethon_phone and config.admin_telegram_id:
        findings.append(Finding(
            "collector_account", "warning",
            "Аккаунт-коллектор и админский аккаунт могут совпадать: "
            "блокировка номера отнимет и сбор данных, и уведомления",
            "Заведите отдельный номер для коллектора",
        ))

    # --- credentials that are still placeholders ----------------------------
    if _is_placeholder(config.yc_folder_id):
        findings.append(Finding(
            "yandex_cloud", "warning",
            "Yandex Cloud не настроен: логи только в контейнере, файлы на локальном диске",
            "Смонтируйте ключ сервисного аккаунта (роли logging.writer, storage.editor)",
        ))
    if _is_placeholder(config.max_bot_token):
        findings.append(Finding(
            "max", "warning",
            "MAX не настроен — кабинет открывается только в Telegram",
            "Задайте MAX_BOT_TOKEN, MAX_BOT_USERNAME и MAX_WEBHOOK_SECRET",
        ))
    if _is_placeholder(config.telegram_bot_token):
        findings.append(Finding(
            "telegram", "blocker",
            "Telegram-бот не настроен — ни уведомлений, ни входа в кабинет",
            "Задайте TELEGRAM_BOT_TOKEN",
        ))

    # --- development settings left on in production -------------------------
    if config.node_env != "production":
        findings.append(Finding(
            "node_env", "warning",
            f"NODE_ENV={config.node_env}: открыт /api/docs, CORS разрешает любой источник",
            "Поставьте NODE_ENV=production",
        ))
    if "dev_password" in (config.database_url or ""):
        findings.append(Finding(
            "db_password", "warning",
            "У базы стоит пароль по умолчанию",
            "Смените пароль re_app и обновите DATABASE_URL",
        ))

    return findings


async def readiness_report(session, agency_id: Optional[str] = None) -> dict:
    """Findings grouped for the go-live check."""
    findings = await collect_findings(session, agency_id)
    blockers = [f for f in findings if f.severity == "blocker"]
    return {
        "ready": not blockers,
        "blockers": len(blockers),
        "warnings": len(findings) - len(blockers),
        "findings": {f.key: f.as_dict() for f in findings},
    }
