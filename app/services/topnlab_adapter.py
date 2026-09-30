"""TopNLab CRM: everything REIP says to TopNLab goes through this module.

ТЗ «Интеграция с TopNLab CRM» v1.0, раздел 4. Документация API — четыре PDF от
TopNLab (основной API, API колл-центра, API задач, API отчётов).

Где лежат реквизиты. ТЗ предлагает шесть колонок в agencies, но у REIP уже есть
agency_crm_config (дополнение Signal Bus §4.3): там appkey шифруется, и его
задаёт владелец в кабинете. Поэтому appkey — это ``api_key`` строки с
connector_type='topnlab', а остальное лежит в её ``config``:

    company_id       ID компании в TopNLab (нужен для ключей Avito)
    virtual_number   виртуальный номер АТС (для журнала звонков, необязателен)
    sync_enabled     флаг агентства; поверх него — общий TOPNLAB_SYNC_ENABLED
    manager_email    кому назначать заявку (transferClient), необязателен
    report_menu_id   id кнопки «Аналитика REIP» в меню TopNLab
    report_token     секрет в адресе вебхука отчёта, по нему же ищется агентство
    avito_credentials_encrypted   ключи досок из TopNLab, зашифрованы

Ответы TopNLab (API колл-центра, раздел 1): 200 + status ok/success — успех;
422 — данные неверны и повтор бесполезен; всё остальное, включая тишину, —
временная ошибка, запрос надо повторить позже. Первое кончается исключением
TopnlabRejected, второе — TopnlabUnavailable, и только его Celery повторяет.
"""
from __future__ import annotations

import base64
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import quote

import httpx
import structlog

from app.config import config

logger = structlog.get_logger()

CONNECTOR_TYPE = "topnlab"
REQUEST_TIMEOUT = 10.0  # ТЗ, раздел 2: столько же TopNLab ждёт ответа вебхука отчёта
COMMENT_LIMIT = 500  # importClient режет комментарий длиннее
TASK_TYPES_CACHE_TTL = 86400
TASK_TYPES_CACHE_KEY = "topnlab_task_types:{agency_id}"
# Время задач TopNLab — московское, без зоны в строке. В Москве нет перехода на
# летнее время с 2014 года, поэтому фиксированный сдвиг точен и не требует
# базы часовых поясов, которой нет в slim-образе.
MSK = timezone(timedelta(hours=3))

# Типы карточек в API задач: 2 — «заявки» при создании задачи (раздел 4),
# 3 — «Заявки: Покупатели» в custom_task_type_cards типа задачи (раздел 1).
TASK_OWNER_TYPE_ORDER = 2
TASK_CARD_BUYER_ORDERS = 3
NOTIFY_MINUTES = 2

# Тип объекта REIP → тип недвижимости TopNLab (flat, room, commerce, house, land, garage).
OBJECT_TYPE_MAP = {
    "apartment": "flat", "studio": "flat", "flat": "flat", "квартира": "flat",
    "room": "room", "комната": "room",
    "house": "house", "townhouse": "house", "cottage": "house", "дом": "house",
    "land": "land", "участок": "land",
    "commercial": "commerce", "commerce": "commerce",
    "garage": "garage",
}
DEFAULT_OBJECT_TYPE = "flat"

SEGMENT_RU = {
    "family": "семья", "investor": "инвестор", "relocant": "переезд",
    "remote_worker": "удалёнщик", "senior": "пенсионер", "alternative": "альтернатива",
    "student_parent": "родитель студента",
}
URGENCY_RU = {"hot": "горячий", "warm": "тёплый", "cold": "холодный"}

# Страница «Заявки - Продажа» в меню отчётов. Ищется по названию, номер —
# запасной вариант: у агентства заказчика это 8, как и в примере документации.
REPORT_PAGE_TITLE = "Заявки - Продажа"
REPORT_PAGE_FALLBACK_ID = 8
REPORT_TITLE = "Аналитика REIP"
REPORT_ORDER = 10


class TopnlabError(Exception):
    """TopNLab did not do what was asked."""


class TopnlabRejected(TopnlabError):
    """422 / status=error: the request itself is wrong, repeating it is useless."""

    def __init__(self, message: str, errors: Any = None):
        super().__init__(message)
        self.errors = errors


class TopnlabUnavailable(TopnlabError):
    """Timeout, network failure or an undocumented answer: retry later."""


@dataclass
class TopnlabSettings:
    agency_id: str
    appkey: str
    base_url: str = ""
    calendar_url: str = ""
    company_id: Optional[str] = None
    virtual_number: Optional[str] = None
    manager_email: Optional[str] = None
    sync_enabled: bool = False
    report_menu_id: Optional[int] = None
    report_token: Optional[str] = None
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        self.base_url = (self.base_url or config.topnlab_base_url).rstrip("/")
        self.calendar_url = (self.calendar_url or config.topnlab_calendar_url).rstrip("/")


def settings_from_config(cfg) -> Optional[TopnlabSettings]:
    """TopnlabSettings from an AgencyCRMConfig row, or None if it is not TopNLab."""
    if cfg is None or (cfg.crm_type or "").lower() != CONNECTOR_TYPE or not cfg.api_key:
        return None
    extra = dict(cfg.config or {})
    menu_id = extra.get("report_menu_id")
    return TopnlabSettings(
        agency_id=str(cfg.agency_id),
        appkey=cfg.api_key,
        base_url=cfg.base_url or "",
        company_id=_str_or_none(extra.get("company_id")),
        virtual_number=_digits_or_none(extra.get("virtual_number")),
        manager_email=_str_or_none(extra.get("manager_email")),
        sync_enabled=bool(extra.get("sync_enabled")),
        report_menu_id=int(menu_id) if str(menu_id or "").isdigit() else None,
        report_token=_str_or_none(extra.get("report_token")),
        extra=extra,
    )


async def load_config(session, agency_id):
    """The agency's active TopNLab row of agency_crm_config, if there is one."""
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.agency_crm_config import AgencyCRMConfig  # noqa: PLC0415

    return (await session.execute(
        select(AgencyCRMConfig).where(
            AgencyCRMConfig.agency_id == agency_id,
            AgencyCRMConfig.connector_type == CONNECTOR_TYPE,
            AgencyCRMConfig.is_active.is_(True),
        ).limit(1)
    )).scalars().first()


def _str_or_none(value: Any) -> Optional[str]:
    text = str(value).strip() if value is not None else ""
    return text or None


def _digits_or_none(value: Any) -> Optional[str]:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits or None


# --------------------------------------------------------------------------- HTTP

def _hide(text: str, appkey: str) -> str:
    """The appkey travels in the query string of GET calls, and httpx puts the URL
    into its error text -- the same leak that once wrote the bot token to logs."""
    return text.replace(appkey, "***") if appkey else text


async def _call(
    s: TopnlabSettings,
    method: str,
    url: str,
    *,
    json: Optional[dict] = None,
    params: Optional[dict] = None,
    what: str,
) -> dict:
    """One request to TopNLab, classified per the documented answer kinds."""
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.request(method, url, json=json, params=params)
    except httpx.HTTPError as e:
        logger.warning("TopNLab unreachable", what=what, agency_id=s.agency_id,
                       error=_hide(f"{type(e).__name__}: {e}", s.appkey)[:300])
        raise TopnlabUnavailable(f"{what}: нет ответа от TopNLab") from None

    try:
        body = resp.json()
    except ValueError:
        body = None

    if resp.status_code == 422 or (resp.status_code == 200 and isinstance(body, dict)
                                   and body.get("status") == "error"):
        errors = body.get("errors") if isinstance(body, dict) else None
        logger.warning("TopNLab rejected request", what=what, agency_id=s.agency_id,
                       status=resp.status_code, errors=errors)
        raise TopnlabRejected(f"{what}: TopNLab отклонил запрос", errors)

    if resp.status_code != 200 or not isinstance(body, dict) \
            or body.get("status") not in ("ok", "success"):
        logger.warning("TopNLab answered unexpectedly", what=what, agency_id=s.agency_id,
                       status=resp.status_code,
                       body=_hide(resp.text[:200], s.appkey))
        raise TopnlabUnavailable(f"{what}: TopNLab ответил {resp.status_code}")

    if body.get("errors"):
        # «Успех с предупреждением»: действие выполнено, необязательные поля — нет.
        logger.warning("TopNLab accepted with warnings", what=what,
                       agency_id=s.agency_id, errors=body.get("errors"))
    return body


def _payload(body: dict) -> Any:
    """Documented as ``data``; the menu pages call answers under ``response``."""
    return body.get("data") if "data" in body else body.get("response")


def _first_id(value: Any) -> Optional[int]:
    """An id out of the shapes TopNLab uses: 5, {"id": 5}, [{"id": 5}]."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    if isinstance(value, dict):
        for key in ("id", "insertedId"):
            found = _first_id(value.get(key))
            if found is not None:
                return found
        return None
    if isinstance(value, list) and value:
        return _first_id(value[0])
    return None


# ------------------------------------------------------------------ lead → заявка

def object_type_for(lead: Any, signal: Any = None) -> str:
    """TopNLab property type the buyer is after; a flat when nobody said."""
    candidates = [
        (getattr(lead, "buyer_profile", None) or {}).get("property_type"),
        (getattr(signal, "ai_analysis", None) or {}).get("property_type") if signal else None,
    ]
    for value in candidates:
        mapped = OBJECT_TYPE_MAP.get(str(value or "").strip().lower())
        if mapped:
            return mapped
    return DEFAULT_OBJECT_TYPE


def _money_k(value: Optional[int]) -> Optional[str]:
    return f"{int(value) // 1000}" if value else None


def _budget(lead: Any) -> Optional[str]:
    lo, hi = _money_k(getattr(lead, "budget_min", None)), _money_k(getattr(lead, "budget_max", None))
    if lo and hi:
        return f"{lo}–{hi}к ₽"
    if hi:
        return f"до {hi}к ₽"
    if lo:
        return f"от {lo}к ₽"
    return None


def _source(lead: Any, signal: Any) -> str:
    source = getattr(signal, "source", None) if signal else None
    if source is not None and getattr(source, "source_name", None):
        return f"{source.source_name} ({source.source_type})"
    return getattr(lead, "source_type", None) or "REIP"


def build_comment(lead: Any, signal: Any = None) -> str:
    """ТЗ 4.2: score, сегмент, срочность, бюджет, источник — и то, по чему
    менеджер найдёт человека: ник, ссылку на сообщение, само сообщение.
    Обрезается до 500 символов с конца, так что режется текст, а не контакт."""
    parts = [f"[REIP] Score: {getattr(lead, 'intent_score', None) or 0}/100"]
    segment = getattr(lead, "segment", None)
    if segment:
        parts.append(f"Сегмент: {SEGMENT_RU.get(segment, segment)}")
    urgency = getattr(lead, "urgency", None)
    if urgency:
        parts.append(f"Срочность: {URGENCY_RU.get(urgency, urgency)}")
    budget = _budget(lead)
    if budget:
        parts.append(f"Бюджет: {budget}")
    parts.append(f"Источник: {_source(lead, signal)}")
    username = getattr(lead, "telegram_username", None)
    if username:
        parts.append(f"Telegram: @{username.lstrip('@')}")
    url = getattr(signal, "signal_url", None) if signal else None
    if url:
        parts.append(f"Сообщение: {url}")
    comment = " | ".join(parts)
    text = " ".join((getattr(signal, "raw_text", None) or "").split()) if signal else ""
    if text:
        comment += f"\n«{text}»"
    if len(comment) > COMMENT_LIMIT:
        comment = comment[:COMMENT_LIMIT - 2].rstrip() + "…»" if text else comment[:COMMENT_LIMIT]
    return comment


def build_client_payload(s: TopnlabSettings, lead: Any, signal: Any = None) -> dict:
    """Body for /call/main/importClient/. REIP ищет покупателей, отсюда action=1."""
    payload = {
        "appkey": s.appkey,
        "fullname": (getattr(lead, "name", None) or "").strip() or "Покупатель из REIP",
        "phone": _digits_or_none(getattr(lead, "phone", None)) or "",
        "action": 1,
        "object_type": object_type_for(lead, signal),
        "comment": build_comment(lead, signal),
    }
    if s.virtual_number:
        # По этому номеру TopNLab определяет «Рекламный источник» карточки,
        # созданной не из звонка (API колл-центра, раздел 6).
        payload["to_number"] = s.virtual_number
    return payload


async def push_lead_to_topnlab(s: TopnlabSettings, lead: Any, signal: Any = None) -> int:
    """ТЗ 4.2: create a buyer order in TopNLab. Returns its insertedId."""
    body = await _call(s, "POST", f"{s.base_url}/call/main/importClient/",
                       json=build_client_payload(s, lead, signal), what="importClient")
    client_id = _first_id(body.get("insertedId"))
    if client_id is None:
        # Заявка, возможно, создана, но без id мы не сможем ни повесить задачу,
        # ни узнать её в отчёте. Повтор создаст дубль — поэтому не повторяем.
        raise TopnlabRejected("importClient: TopNLab не вернул insertedId", body)
    return client_id


# ------------------------------------------------------------ задача «Позвонить»

async def _cache_get(key: str) -> Optional[list]:
    import json as _json  # noqa: PLC0415

    import redis.asyncio as redis  # noqa: PLC0415

    client = redis.from_url(config.redis_url, socket_connect_timeout=2, socket_timeout=2)
    try:
        raw = await client.get(key)
        return _json.loads(raw) if raw else None
    except Exception as e:  # noqa: BLE001 - без кэша просто спросим TopNLab
        logger.warning("TopNLab task types cache unavailable", error=str(e)[:120])
        return None
    finally:
        await client.aclose()


async def _cache_set(key: str, value: list) -> None:
    import json as _json  # noqa: PLC0415

    import redis.asyncio as redis  # noqa: PLC0415

    client = redis.from_url(config.redis_url, socket_connect_timeout=2, socket_timeout=2)
    try:
        await client.set(key, _json.dumps(value, ensure_ascii=False), ex=TASK_TYPES_CACHE_TTL)
    except Exception as e:  # noqa: BLE001
        logger.warning("TopNLab task types not cached", error=str(e)[:120])
    finally:
        await client.aclose()


async def get_topnlab_task_types(s: TopnlabSettings, *, use_cache: bool = True) -> list[dict]:
    """ТЗ 4.4: task types of the agency, cached in Redis for a day."""
    key = TASK_TYPES_CACHE_KEY.format(agency_id=s.agency_id)
    if use_cache:
        cached = await _cache_get(key)
        if cached is not None:
            return cached
    body = await _call(s, "GET", f"{s.calendar_url}/api/partners/tasks/get-task-types",
                       params={"appkey": s.appkey}, what="get-task-types")
    types = _payload(body)
    types = [t for t in types if isinstance(t, dict)] if isinstance(types, list) else []
    await _cache_set(key, types)
    return types


def find_call_task_type(types: list[dict]) -> Optional[int]:
    """The «Позвонить» type usable on buyer orders.

    ТЗ asks for a name containing «позвон». A type hidden from manual choice or
    not allowed on buyer orders would make TopNLab refuse the task, so those are
    passed over while a better one exists.
    """
    calls = [t for t in types if "позвон" in str(t.get("name", "")).lower()]

    def usable(t: dict) -> bool:
        cards = t.get("custom_task_type_cards") or []
        return not t.get("is_hidden") and (not cards or TASK_CARD_BUYER_ORDERS in cards)

    for pool in ([t for t in calls if usable(t)], calls):
        for t in pool:
            found = _first_id(t.get("id"))
            if found is not None:
                return found
    return None


def _msk(moment: datetime) -> str:
    return moment.astimezone(MSK).strftime("%Y-%m-%d %H:%M:%S")


async def create_topnlab_task(
    s: TopnlabSettings,
    topnlab_client_id: int,
    lead: Any,
    minutes_delay: Optional[int] = None,
    *,
    now: Optional[datetime] = None,
) -> Optional[int]:
    """ТЗ 4.3: task «Позвонить» on the order, starting in N minutes, 30 minutes long.

    Returns the task id, or None when the agency has no call task type at all --
    that is a setting to fix in TopNLab, not something a retry would cure.
    """
    type_id = find_call_task_type(await get_topnlab_task_types(s))
    if type_id is None:
        logger.warning("TopNLab has no «Позвонить» task type", agency_id=s.agency_id)
        return None
    delay = config.topnlab_task_delay_minutes if minutes_delay is None else minutes_delay
    begin = (now or datetime.now(timezone.utc)) + timedelta(minutes=delay)
    urgency = getattr(lead, "urgency", None)
    segment = getattr(lead, "segment", None)
    description = (
        f"Горячий лид из REIP! Score: {getattr(lead, 'intent_score', None) or 0}/100\n"
        f"Сегмент: {SEGMENT_RU.get(segment, segment or '—')} | "
        f"{URGENCY_RU.get(urgency, urgency or '—').upper()}"
    )
    body = await _call(s, "POST", f"{s.calendar_url}/api/partners/tasks/create", json={
        "appkey": s.appkey,
        "owner_id": topnlab_client_id,
        "owner_type": TASK_OWNER_TYPE_ORDER,
        "task_type_id": type_id,
        "begin_at": _msk(begin),
        "end_at": _msk(begin + timedelta(minutes=30)),
        "description": description,
        "notify_before_value": "5",
        "notify_before_type": NOTIFY_MINUTES,
    }, what="tasks/create")
    return _first_id(_payload(body))


# ------------------------------------------------------ звонок, менеджер, ключи

async def log_signal_as_call(s: TopnlabSettings, topnlab_client_id: int, signal: Any) -> bool:
    """ТЗ 4.5: the signal as an unanswered incoming call, for source analytics.

    Not critical: never raises. Without the agency's virtual number there is
    nothing to put in to_number, so the call is not logged at all.
    """
    if not s.virtual_number:
        return False
    started = getattr(signal, "created_at", None) or datetime.now(timezone.utc)
    start_time = int(started.timestamp())
    try:
        await _call(s, "POST", f"{s.base_url}/call/main/importCall/", json={
            "appkey": s.appkey,
            "from_number": "",
            "to_number": s.virtual_number,
            "direction": "income",
            "start_time": start_time,
            "end_time": start_time + 60,
            "answered": 0,
            "bind_to_client_id": topnlab_client_id,
        }, what="importCall")
        return True
    except TopnlabError as e:
        logger.info("Signal not logged as a TopNLab call", agency_id=s.agency_id, error=str(e))
        return False


async def transfer_to_manager(s: TopnlabSettings, topnlab_client_id: int,
                              manager_email: Optional[str] = None) -> bool:
    """ТЗ 4.6: make a manager responsible for the order. Never raises."""
    email = manager_email or s.manager_email
    if not email:
        return False
    try:
        await _call(s, "POST", f"{s.base_url}/call/main/transferClient/", json={
            "appkey": s.appkey, "client_id": topnlab_client_id, "user_mail": email,
        }, what="transferClient")
        return True
    except TopnlabError as e:
        logger.info("TopNLab order not transferred", agency_id=s.agency_id, error=str(e))
        return False


async def get_avito_credentials(s: TopnlabSettings, site: str = "AVITO") -> Any:
    """ТЗ 4.7: the agency's classifieds credentials as TopNLab keeps them."""
    if not s.company_id:
        raise TopnlabRejected("Не задан ID компании в TopNLab")
    body = await _call(
        s, "POST", f"{s.base_url}/public/partner/{quote(s.company_id, safe='')}/credentials",
        params={"site": site, "key": s.appkey}, what="partner/credentials")
    return _payload(body)


def encrypt_blob(value: Any) -> str:
    """JSON value → encrypted text fit for a JSONB field."""
    import json as _json  # noqa: PLC0415

    from app.services.encryption import encrypt_pii  # noqa: PLC0415

    raw = encrypt_pii(_json.dumps(value, ensure_ascii=False))
    return base64.b64encode(raw).decode("ascii")


def decrypt_blob(value: Optional[str]) -> Any:
    import json as _json  # noqa: PLC0415

    from app.services.encryption import decrypt_pii  # noqa: PLC0415

    if not value:
        return None
    return _json.loads(decrypt_pii(base64.b64decode(value)))


# ---------------------------------------------------------- отчёт «Аналитика REIP»

def report_webhook_url(token: str) -> str:
    return f"{config.base_url.rstrip('/')}/api/topnlab/report-webhook?token={token}"


async def find_report_page(s: TopnlabSettings) -> int:
    body = await _call(s, "GET", f"{s.base_url}/public/menu/get-all-pages",
                       params={"key": s.appkey}, what="menu/get-all-pages")
    pages = _payload(body)
    if isinstance(pages, dict):
        for page_id, title in pages.items():
            if str(title).strip().lower() == REPORT_PAGE_TITLE.lower() and str(page_id).isdigit():
                return int(page_id)
    return REPORT_PAGE_FALLBACK_ID


async def list_reports(s: TopnlabSettings) -> list[dict]:
    body = await _call(s, "POST", f"{s.base_url}/public/menu/list/",
                       json={"appkey": s.appkey}, what="menu/list")
    items = _payload(body)
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []


async def register_reip_report(s: TopnlabSettings) -> tuple[int, str, bool]:
    """ТЗ 4.8: put «Аналитика REIP» into TopNLab's mass-action menu.

    Returns (menu id, token, created). Registering twice must not leave two
    buttons: if the menu already holds our current address, that entry is kept.
    The token in the address is what the webhook trusts -- TopNLab signs nothing,
    and without it anyone who learnt the URL could pull the agency's leads.
    """
    token = s.report_token or secrets.token_urlsafe(24)
    url = report_webhook_url(token)
    try:
        existing = await list_reports(s)
    except TopnlabRejected:
        existing = []
    for item in existing:
        if str(item.get("url", "")) == url and _first_id(item.get("id")) is not None:
            return _first_id(item.get("id")), token, False

    page_id = await find_report_page(s)
    body = await _call(s, "GET", f"{s.base_url}/public/menu/create", params={
        "key": s.appkey, "title": REPORT_TITLE, "page_id": page_id,
        "order": REPORT_ORDER, "url": url,
    }, what="menu/create")
    menu_id = _first_id(_payload(body)) or _first_id(body)
    if menu_id is None:
        # Кнопка могла появиться — найдём её по адресу, а не будем плодить вторую.
        for item in await list_reports(s):
            if str(item.get("url", "")) == url:
                menu_id = _first_id(item.get("id"))
    if menu_id is None:
        raise TopnlabRejected("menu/create: TopNLab не вернул id отчёта", body)
    return menu_id, token, True


async def check_connection(s: TopnlabSettings) -> int:
    """ТЗ 8.2 «Проверить подключение»: the key works if task types come back."""
    return len(await get_topnlab_task_types(s, use_cache=False))


# ------------------------------------------------------------------ весь поток

async def sync_lead_to_topnlab(session, lead, *, force: bool = False) -> dict:
    """ТЗ 6.2 and 11: order → task «Позвонить» → manager → call log.

    Each step records its result on the lead before the next one starts, so a
    retry picks up where the last attempt stopped instead of creating a second
    order. ``force`` skips the score threshold: it is used when a manager marks
    a lead qualified by hand, which is a stronger signal than any score.

    Raises TopnlabUnavailable for the caller to retry; everything else is
    reported in the returned dict.
    """
    from app.models.signal import Signal  # noqa: PLC0415

    if not config.topnlab_sync_enabled:
        return {"exported": False, "reason": "disabled_globally"}
    s = settings_from_config(await load_config(session, lead.agency_id))
    if s is None:
        return {"exported": False, "reason": "not_configured"}
    if not s.sync_enabled:
        return {"exported": False, "reason": "disabled_for_agency"}
    if not lead.consent_given:
        return {"exported": False, "reason": "no_consent"}
    if lead.topnlab_client_id and lead.topnlab_task_id:
        return {"exported": True, "reason": "already_synced",
                "topnlab_client_id": lead.topnlab_client_id}
    if not force and not lead.topnlab_client_id \
            and (lead.intent_score or 0) < config.topnlab_lead_min_score:
        return {"exported": False, "reason": "below_threshold"}

    signal_id = lead.source_signal_id or lead.signal_id
    signal = await session.get(Signal, signal_id) if signal_id else None

    created_now = False
    if not lead.topnlab_client_id:
        try:
            client_id = await push_lead_to_topnlab(s, lead, signal)
        except TopnlabRejected as e:
            return {"exported": False, "reason": "rejected", "errors": e.errors}
        lead.topnlab_client_id = client_id
        lead.topnlab_synced_at = datetime.now(timezone.utc)
        if not lead.crm_deal_id:
            # Та же цепочка атрибуции, что у других CRM: сигнал → лид → заявка.
            lead.crm_deal_id = str(client_id)
        await session.commit()
        created_now = True
        logger.info("Lead pushed to TopNLab", lead_id=str(lead.id), topnlab_client_id=client_id)

    result = {"exported": True, "topnlab_client_id": lead.topnlab_client_id,
              "crm_deal_id": lead.crm_deal_id}

    if created_now:
        result["transferred"] = await transfer_to_manager(s, lead.topnlab_client_id)

    try:
        task_id = await create_topnlab_task(s, lead.topnlab_client_id, lead)
    except TopnlabRejected as e:
        task_id = None
        result["task_error"] = str(e)
    if task_id:
        lead.topnlab_task_id = task_id
        await session.commit()
    result["topnlab_task_id"] = task_id

    if created_now and signal is not None:
        result["call_logged"] = await log_signal_as_call(s, lead.topnlab_client_id, signal)
    return result
