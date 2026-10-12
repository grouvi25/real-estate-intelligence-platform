"""Buttons for the platform operators in the sales bot.

Typing /approve_3f2a9c1e is prone to mistakes and nobody remembers the ids, so
the operator drives everything with buttons: a menu (/start, /menu), a card per
request with the next step on it, a card per agency, the demo toggle. A new
request arrives with its buttons already attached. The text commands
(sales_bot.handle_operator_command) stay as they were; the buttons call the
same handlers, so both ways do exactly the same thing.

Callback data is "<action>:<id>[:<arg>]" with the first 8 characters of the id,
well inside Telegram's 64-byte limit.
"""
from __future__ import annotations

import re
from typing import Optional

import structlog

logger = structlog.get_logger()

PLAN_LABELS = {"start": "Start", "pro": "Pro", "isolated": "Isolated"}
REQUEST_STATUS = {"pending": "новая", "payment_pending": "ждёт оплату", "paid": "оплачена",
                  "completed": "подключена", "rejected": "отклонена"}
OPEN_REQUESTS = ("pending", "payment_pending", "paid")


def keyboard(rows: list[list[tuple[str, str]]]) -> dict:
    return {"inline_keyboard": [[{"text": text, "callback_data": data} for text, data in row]
                                for row in rows if row]}


MENU_TEXT = ("Панель оператора REIP.\n\n"
             "Заявки — новые агентства: одобрить, отметить оплату, подключить.\n"
             "Агентства — продлить подписку или заблокировать.\n"
             "Демо — включить или выключить демо-ссылку.")
MENU = keyboard([[("📋 Заявки", "m:req"), ("🏢 Агентства", "m:ag")], [("🎬 Демо", "m:demo")]])


def request_text(req) -> str:
    lines = [f"Заявка {str(req.id)[:8]} · {REQUEST_STATUS.get(req.status, req.status)}",
             f"Агентство: {req.agency_name}", f"Город: {req.city_name}",
             f"Тариф: {PLAN_LABELS.get(req.plan_id, req.plan_id)}"]
    contact = []
    if req.display_name:
        contact.append(req.display_name)
    if req.username:
        contact.append(f"@{req.username}")
    if req.phone:
        contact.append(f"+{req.phone}")
    if contact:
        lines.append("Контакт: " + ", ".join(contact))
    if not req.telegram_id:
        lines.append("Заявка с демо-страницы: Telegram нет, звонить.")
    hint = {"pending": "Чтобы одобрить, выберите тариф — клиенту уйдут тариф и цена.",
            "payment_pending": "Когда клиент оплатит счёт, нажмите «Оплата получена».",
            "paid": "Оплачено — подключите агентство, владелец получит ссылку в кабинет."}.get(req.status)
    if hint:
        lines += ["", hint]
    return "\n".join(lines)


def request_buttons(req, back: bool = True) -> dict:
    rid = str(req.id)[:8]
    rows: list[list[tuple[str, str]]] = []
    if req.status == "pending":
        rows.append([(f"✅ {label}", f"ap:{rid}:{plan}") for plan, label in PLAN_LABELS.items()])
    if req.status == "payment_pending":
        rows.append([("💰 Оплата получена", f"pd:{rid}")])
        rows.append([(f"Тариф → {label}", f"ap:{rid}:{plan}") for plan, label in PLAN_LABELS.items()
                     if plan != req.plan_id])
    if req.status == "paid":
        rows.append([("🏢 Подключить агентство", f"cr:{rid}")])
    if req.status in ("pending", "payment_pending"):
        rows.append([("✖ Отклонить", f"rj:{rid}")])
    if back:
        rows.append([("⬅ Все заявки", "m:req")])
    return keyboard(rows)


def agency_text(agency) -> str:
    until = agency.subscription_expires_at
    return "\n".join([
        f"{agency.name} · {agency.base_city or '—'}",
        f"Тариф: {agency.subscription_plan}",
        "Оплачено до: " + (f"{until:%d.%m.%Y}" if until else "без срока"),
        "Кабинет: " + ("работает" if agency.subscription_active else "⛔ заблокирован"),
    ])


def agency_buttons(agency) -> dict:
    aid = str(agency.id)[:8]
    return keyboard([
        [("+1 мес.", f"ex:{aid}:1"), ("+3 мес.", f"ex:{aid}:3"), ("+12 мес.", f"ex:{aid}:12")],
        [("⛔ Заблокировать", f"sp:{aid}")] if agency.subscription_active
        else [("✅ Разблокировать", f"us:{aid}")],
        [("⬅ Все агентства", "m:ag")],
    ])


# ------------------------------------------------------------------ screens

async def requests_screen(session) -> tuple[str, dict]:
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.billing import OnboardingRequest  # noqa: PLC0415

    rows = (await session.execute(select(OnboardingRequest).where(
        OnboardingRequest.status.in_(OPEN_REQUESTS)
    ).order_by(OnboardingRequest.created_at.desc()).limit(15))).scalars().all()
    if not rows:
        return "Открытых заявок нет. Новые придут сюда сами, с кнопками.", keyboard([[("⬅ Меню", "m:menu")]])
    buttons = [[(f"{r.agency_name[:28]} · {r.city_name} · {REQUEST_STATUS.get(r.status, r.status)}",
                 f"rq:{str(r.id)[:8]}")] for r in rows]
    return "Открытые заявки — нажмите, чтобы открыть:", keyboard(buttons + [[("⬅ Меню", "m:menu")]])


async def agencies_screen(session) -> tuple[str, dict]:
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.agency import Agency  # noqa: PLC0415

    rows = (await session.execute(select(Agency).order_by(Agency.name).limit(30))).scalars().all()
    if not rows:
        return "Агентств пока нет.", keyboard([[("⬅ Меню", "m:menu")]])
    buttons = []
    for a in rows:
        until = f"до {a.subscription_expires_at:%d.%m}" if a.subscription_expires_at else "без срока"
        mark = "" if a.subscription_active else "⛔ "
        buttons.append([(f"{mark}{a.name[:30]} · {until}", f"ag:{str(a.id)[:8]}")])
    return "Агентства — нажмите, чтобы открыть:", keyboard(buttons + [[("⬅ Меню", "m:menu")]])


async def demo_screen(session, op_id: int, switch: Optional[str] = None) -> tuple[str, dict]:
    from app.services.sales_bot import _cmd_demo  # noqa: PLC0415

    text = await _cmd_demo(session, op_id, switch or "", [])
    enabled = text.startswith("Демо-режим включён")
    button = ("⏸ Выключить демо", "dm:off") if enabled else ("▶ Включить демо", "dm:on")
    return text, keyboard([[button], [("⬅ Меню", "m:menu")]])


# ------------------------------------------------------------------ callbacks

async def _request_any(session, rid: str):
    from app.services.onboarding import find_request  # noqa: PLC0415

    return await find_request(session, rid, tuple(REQUEST_STATUS))


async def _agency(session, aid: str):
    from app.services.onboarding import find_agency  # noqa: PLC0415

    return await find_agency(session, aid)


async def screen_for(session, op_id: int, data: str) -> tuple[str, dict]:
    """What the message becomes after a press: (text, keyboard)."""
    from app.services import sales_bot as sb  # noqa: PLC0415

    action, _, rest = data.partition(":")
    target, _, arg = rest.partition(":")

    if action == "m":
        if target == "req":
            return await requests_screen(session)
        if target == "ag":
            return await agencies_screen(session)
        if target == "demo":
            return await demo_screen(session, op_id)
        return MENU_TEXT, MENU
    if action == "dm":
        return await demo_screen(session, op_id, target)

    if action in ("rq", "ap", "pd", "cr", "rj", "rjy"):
        result = ""
        if action == "ap":
            result = await sb._cmd_approve(session, op_id, target, [arg])
        elif action == "pd":
            result = await sb._cmd_paid(session, op_id, target, [])
        elif action == "cr":
            result = await sb._cmd_create(session, op_id, target, [])
        elif action == "rjy":
            result = await sb._cmd_reject(session, op_id, target, [])
        req = await _request_any(session, target)
        if req is None:
            return "Заявка не найдена — возможно, её уже обработали.", keyboard([[("⬅ Все заявки", "m:req")]])
        if action == "rj":
            return (request_text(req) + "\n\nОтклонить заявку? Клиенту уйдёт вежливый отказ.",
                    keyboard([[("Да, отклонить", f"rjy:{target}"), ("Отмена", f"rq:{target}")]]))
        text = request_text(req) + (f"\n\n{_short(result)}" if result else "")
        return text, request_buttons(req)

    if action in ("ag", "ex", "sp", "spy", "us"):
        result = ""
        if action == "ex":
            result = await sb._cmd_extend(session, op_id, target, [arg])
        elif action == "spy":
            result = await sb._cmd_suspend(session, op_id, target, [])
        elif action == "us":
            result = await sb._cmd_unsuspend(session, op_id, target, [])
        agency = await _agency(session, target)
        if agency is None:
            return "Агентство не найдено.", keyboard([[("⬅ Все агентства", "m:ag")]])
        if action == "sp":
            return (agency_text(agency) + "\n\nЗаблокировать кабинет и остановить сбор?",
                    keyboard([[("Да, заблокировать", f"spy:{target}"), ("Отмена", f"ag:{target}")]]))
        return agency_text(agency) + (f"\n\n✅ {result}" if result else ""), agency_buttons(agency)

    return MENU_TEXT, MENU


# "После оплаты — /paid_ab12cd34", "Создать агентство: /create_ab12cd34 [токен бота]"
_NEXT_COMMAND = re.compile(
    r"\s*(После оплаты\s*—|Создать агентство:|Включить:)?\s*/[a-z]+(_\S+)?(\s*\[[^\]]*\])?\.?")


def _short(result: str) -> str:
    """The text commands end with the next command to type; the buttons replace it."""
    text = "\n".join(_NEXT_COMMAND.sub("", line).rstrip() for line in result.splitlines()).strip()
    return f"✅ {text}" if text else ""


async def handle_callback(cq: dict) -> None:
    from app.database import async_session  # noqa: PLC0415
    from app.dependencies import is_platform_operator  # noqa: PLC0415
    from app.services import sales_bot as sb  # noqa: PLC0415

    uid = (cq.get("from") or {}).get("id")
    message = cq.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    if not uid or not await is_platform_operator(int(uid)):
        await sb.call("answerCallbackQuery", {"callback_query_id": cq.get("id"),
                                              "text": "Эти кнопки — только для операторов REIP"})
        return
    await sb.call("answerCallbackQuery", {"callback_query_id": cq.get("id")})
    try:
        async with async_session() as session:
            text, markup = await screen_for(session, int(uid), cq.get("data") or "")
    except Exception as e:  # noqa: BLE001 - the operator sees why, the bot keeps running
        logger.error("Operator button failed", data=cq.get("data"), error=str(e)[:300])
        text, markup = f"Не получилось: {e}", keyboard([[("⬅ Меню", "m:menu")]])
    edited = chat_id and message.get("message_id") and await sb.call("editMessageText", {
        "chat_id": chat_id, "message_id": message["message_id"], "text": text[:4000],
        "reply_markup": markup, "disable_web_page_preview": True})
    if not edited:
        await sb.send(int(uid), text, markup)
