"""The platform's sales bot and the operator's commands in it. ТЗ «SaaS-слой» 5.3-5.5.

Not a client bot: it talks to agencies that want to buy REIP. A prospect gives
the city (checked for being free), the agency name and a phone; the request
lands with the operators, who drive it on from the same chat:

    /requests                     open requests
    /approve_<id> [start|pro|isolated]  send a payment link (ЮKassa) or payment details
    /paid_<id>                    payment received outside ЮKassa
    /create_<id> [bot_token]      create the agency; the owner gets the invite link
    /reject_<id>                  decline
    /extend_<agency> <months>     extend a subscription
    /suspend_<agency>, /unsuspend_<agency>

Ids are the first 8 characters, as printed in the notifications. Conversation
state lives in Redis for a week; nothing about a prospect is written to the
database until they send a phone number, and that phone is stored encrypted.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Optional

import structlog

from app.config import config

logger = structlog.get_logger()

STATE_KEY = "saas_ob:{uid}"
STATE_TTL = 7 * 24 * 3600
PLANS = ("start", "pro", "isolated")

GREETING = (
    "Здравствуйте! Я помогу подключить REIP для вашего агентства.\n\n"
    "REIP находит в открытых чатах людей, которые собираются купить недвижимость, "
    "оценивает их через ИИ и передаёт менеджерам готовые лиды. Один город — одно "
    "агентство: конкуренты в вашем городе подключиться уже не смогут.\n\n"
    "В каком городе работает ваше агентство?"
)
CITY_FREE = "Город {city} свободен.\n\nКак называется ваше агентство?"
CITY_TAKEN = ("{reason}\n\nЕсли вы работаете и в другом городе — напишите его. "
              "Или оставьте сообщение, мы ответим.")
ASK_PHONE = ("Последний шаг — телефон для связи. Нажмите «Отправить номер» или напишите его.\n\n"
             "Отправляя номер, вы соглашаетесь на его обработку для связи по заявке (152-ФЗ).")
SUBMITTED = ("Заявка принята.\n\nАгентство: {agency}\nГород: {city}\n\n"
             "Мы свяжемся с вами в течение рабочего дня.")
BAD_PHONE = "Не похоже на номер телефона. Напишите его цифрами, например +7 918 123-45-67."


# ------------------------------------------------------------------ transport

async def send(chat_id: int, text: str, reply_markup: Optional[dict] = None) -> bool:
    """Through the sales bot. Never raises: a lost message is logged, not fatal."""
    from app.services.bot_abstraction import _redact, bot_layer  # noqa: PLC0415

    token = config.platform_onboarding_bot_token
    if not token:
        logger.warning("Sales bot token is not set, message not sent")
        return False
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text[:4000],
                               "disable_web_page_preview": True}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        resp = await asyncio.wait_for(bot_layer.telegram_http.post(
            f"https://api.telegram.org/bot{token}/sendMessage", json=payload), timeout=20)
        return bool(resp.json().get("ok"))
    except Exception as e:  # noqa: BLE001
        logger.warning("Sales bot send failed", error=_redact(str(e))[:200])
        return False


async def notify_operators(text: str) -> None:
    from sqlalchemy import select  # noqa: PLC0415

    from app.database import async_session  # noqa: PLC0415
    from app.models.billing import PlatformOperator  # noqa: PLC0415

    ids = set(config.operator_telegram_ids)
    try:
        async with async_session() as session:
            ids |= set((await session.execute(select(PlatformOperator.telegram_id).where(
                PlatformOperator.is_active.is_(True)))).scalars())
    except Exception as e:  # noqa: BLE001
        logger.warning("Operators list unavailable", error=str(e)[:120])
    for op in ids:
        await send(op, text)


async def _redis():
    import redis.asyncio as redis  # noqa: PLC0415

    return redis.from_url(config.redis_url, socket_connect_timeout=2, socket_timeout=2)


async def get_state(uid: int) -> Optional[dict]:
    client = await _redis()
    try:
        raw = await client.get(STATE_KEY.format(uid=uid))
        return json.loads(raw) if raw else None
    finally:
        await client.aclose()


async def set_state(uid: int, state: Optional[dict]) -> None:
    client = await _redis()
    try:
        if state is None:
            await client.delete(STATE_KEY.format(uid=uid))
        else:
            await client.set(STATE_KEY.format(uid=uid), json.dumps(state, ensure_ascii=False),
                             ex=STATE_TTL)
    finally:
        await client.aclose()


# ------------------------------------------------------------------ prospect

def _phone(text: str) -> Optional[str]:
    digits = re.sub(r"\D", "", text or "")
    if len(digits) == 11 and digits[0] in "78":
        return "7" + digits[1:]
    if len(digits) == 10:
        return "7" + digits
    return None


async def handle_update(update: dict) -> None:
    """Entry point for every sales bot update (polling or webhook)."""
    from app.dependencies import is_platform_operator  # noqa: PLC0415

    msg = update.get("message") or {}
    user = msg.get("from") or {}
    uid = user.get("id")
    if not uid or (msg.get("chat") or {}).get("type", "private") != "private":
        return
    text = (msg.get("text") or "").strip()
    if text.startswith("/") and not text.startswith("/start") and await is_platform_operator(int(uid)):
        await handle_operator_command(int(uid), text)
        return
    await handle_prospect(int(uid), user, text, msg.get("contact"))


async def handle_prospect(uid: int, user: dict, text: str, contact: Optional[dict] = None) -> None:
    from app.database import async_session  # noqa: PLC0415
    from app.services.onboarding import check_city_availability  # noqa: PLC0415

    state = await get_state(uid)
    if text.startswith("/start") or state is None:
        await set_state(uid, {"step": "city"})
        await send(uid, GREETING)
        return

    step = state.get("step")
    if step == "city":
        async with async_session() as session:
            check = await check_city_availability(session, text)
        if not check.available:
            await send(uid, CITY_TAKEN.format(reason=check.reason))
            return
        await set_state(uid, {"step": "name", "city": check.city})
        await send(uid, CITY_FREE.format(city=check.city))
    elif step == "name":
        if len(text) < 2:
            await send(uid, "Напишите, пожалуйста, название агентства.")
            return
        await set_state(uid, {**state, "step": "phone", "agency": text[:200]})
        await send(uid, ASK_PHONE, {"keyboard": [[{"text": "Отправить номер", "request_contact": True}]],
                                    "resize_keyboard": True, "one_time_keyboard": True})
    elif step == "phone":
        phone = _phone((contact or {}).get("phone_number") or text)
        if phone is None:
            await send(uid, BAD_PHONE)
            return
        await _submit(uid, user, state, phone)
    else:
        await send(uid, "Заявка уже у нас, скоро ответим. Начать заново — /start")


async def _submit(uid: int, user: dict, state: dict, phone: str) -> None:
    from app.database import async_session  # noqa: PLC0415
    from app.models.billing import OnboardingRequest  # noqa: PLC0415

    name = " ".join(p for p in (user.get("first_name"), user.get("last_name")) if p) or None
    async with async_session() as session:
        req = OnboardingRequest(telegram_id=uid, username=user.get("username"), display_name=name,
                                city_name=state["city"], agency_name=state["agency"],
                                plan_id="start", status="pending")
        req.phone = phone
        session.add(req)
        await session.commit()
        rid = str(req.id)[:8]
    await set_state(uid, {"step": "done"})
    await send(uid, SUBMITTED.format(agency=state["agency"], city=state["city"]),
               {"remove_keyboard": True})
    await notify_operators(
        f"Новая заявка на REIP\nАгентство: {state['agency']}\nГород: {state['city']}\n"
        f"Telegram: @{user.get('username') or uid}\nТелефон: +{phone}\n\n"
        f"/approve_{rid} — отправить ссылку на оплату (тариф: start, pro, isolated)\n"
        f"/reject_{rid} — отклонить")


# ------------------------------------------------------------------ operator

async def handle_operator_command(op_id: int, text: str) -> None:
    from app.database import async_session  # noqa: PLC0415

    head, _, rest = text.partition(" ")
    command, _, target = head.lstrip("/").partition("_")
    args = rest.split()
    handlers = {
        "requests": _cmd_requests, "approve": _cmd_approve, "paid": _cmd_paid,
        "create": _cmd_create, "reject": _cmd_reject, "extend": _cmd_extend,
        "suspend": _cmd_suspend, "unsuspend": _cmd_unsuspend,
    }
    handler = handlers.get(command.split("@")[0])
    if handler is None:
        await send(op_id, "Команды: /requests, /approve_<id> [тариф], /paid_<id>, /create_<id> [токен бота], "
                          "/reject_<id>, /extend_<агентство> <мес>, /suspend_<агентство>, /unsuspend_<агентство>")
        return
    try:
        async with async_session() as session:
            reply = await handler(session, op_id, target, args)
    except Exception as e:  # noqa: BLE001 - the operator sees why, the bot keeps running
        logger.error("Operator command failed", command=command, error=str(e)[:300])
        reply = f"Не получилось: {e}"
    await send(op_id, reply)


async def _request(session, target: str, statuses: tuple[str, ...]):
    from app.services.onboarding import find_request  # noqa: PLC0415

    req = await find_request(session, target, statuses)
    if req is None:
        raise ValueError(f"заявка {target} не найдена среди: {', '.join(statuses)}")
    return req


async def _cmd_requests(session, op_id, target, args) -> str:
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.billing import OnboardingRequest  # noqa: PLC0415

    rows = (await session.execute(select(OnboardingRequest).where(
        OnboardingRequest.status.in_(("pending", "payment_pending", "paid"))
    ).order_by(OnboardingRequest.created_at.desc()).limit(20))).scalars().all()
    if not rows:
        return "Открытых заявок нет."
    return "\n".join(f"{str(r.id)[:8]} · {r.status} · {r.plan_id} · {r.city_name} · {r.agency_name}"
                     for r in rows)


async def _cmd_approve(session, op_id, target, args) -> str:
    from app.models.billing import SubscriptionPlan  # noqa: PLC0415
    from app.services import yookassa  # noqa: PLC0415

    req = await _request(session, target, ("pending", "payment_pending"))
    if args:
        if args[0] not in PLANS:
            raise ValueError(f"тариф — один из {', '.join(PLANS)}")
        req.plan_id = args[0]
    plan = await session.get(SubscriptionPlan, req.plan_id)
    if config.billing_enabled:
        req.payment_id, req.payment_link = await yookassa.create_payment(req, plan)
        pay_text = f"Оплатить подключение можно по ссылке:\n{req.payment_link}"
    else:
        req.payment_link = None
        pay_text = "Реквизиты для оплаты пришлёт наш менеджер."
    req.status = "payment_pending"
    await session.commit()
    await send(req.telegram_id,
               f"Заявка одобрена. Тариф «{plan.name}», подключение — {plan.one_time_price:,} ₽"
               .replace(",", " ") + (f", далее {plan.monthly_price:,} ₽ в месяц".replace(",", " ")
                                      if plan.monthly_price else "") + f".\n\n{pay_text}")
    return f"Заявка {target}: ссылка отправлена ({plan.id})." if config.billing_enabled else \
        f"Заявка {target}: ЮKassa не настроена, клиенту сказано ждать реквизиты. После оплаты — /paid_{target}"


async def _cmd_paid(session, op_id, target, args) -> str:
    from app.models.billing import BillingEvent, SubscriptionPlan  # noqa: PLC0415

    req = await _request(session, target, ("pending", "payment_pending"))
    plan = await session.get(SubscriptionPlan, req.plan_id)
    req.status = "paid"
    session.add(BillingEvent(onboarding_request_id=req.id, event_type="payment",
                             amount_rub=plan.one_time_price, payment_method="manual",
                             created_by=f"operator:{op_id}",
                             note=f"Оплата подключения по заявке {target} вне ЮKassa"))
    await session.commit()
    return f"Заявка {target} оплачена. Создать агентство: /create_{target} [токен бота агентства]"


async def _cmd_create(session, op_id, target, args) -> str:
    from app.services.onboarding import create_agency_from_onboarding  # noqa: PLC0415

    statuses = ("paid", "pending", "payment_pending") if config.platform_trial_days > 0 else ("paid",)
    req = await _request(session, target, statuses)
    trial = config.platform_trial_days if req.status != "paid" else 0
    agency, link = await create_agency_from_onboarding(
        session, req, bot_token=args[0] if args else None, trial_days=trial,
        operator=f"operator:{op_id}")
    await send(req.telegram_id,
               "Готово, REIP подключён.\n\nОткройте кабинет по ссылке — вы войдёте как владелец. "
               f"Её же отправьте менеджерам:\n{link}\n\nПервым делом загрузите каталог объектов "
               "(Объекты → «Загрузить каталог»): без него подбирать покупателям нечего.")
    return f"Агентство создано: {agency.name}, id {str(agency.id)[:8]}. Ссылка владельцу отправлена."


async def _cmd_reject(session, op_id, target, args) -> str:
    req = await _request(session, target, ("pending", "payment_pending"))
    req.status = "rejected"
    await session.commit()
    await send(req.telegram_id, "Спасибо за интерес к REIP. Сейчас подключить ваш город мы не можем — "
                                "напишите, если хотите обсудить детали.")
    return f"Заявка {target} отклонена."


async def _agency(session, target):
    from app.services.onboarding import find_agency  # noqa: PLC0415

    agency = await find_agency(session, target)
    if agency is None:
        raise ValueError(f"агентство {target} не найдено")
    return agency


async def _cmd_extend(session, op_id, target, args) -> str:
    from app.services.onboarding import extend_subscription  # noqa: PLC0415

    if not args or not args[0].isdigit():
        raise ValueError("укажите число месяцев: /extend_<агентство> 3")
    agency = await extend_subscription(session, await _agency(session, target), int(args[0]),
                                       created_by=f"operator:{op_id}")
    return f"{agency.name}: оплачено до {agency.subscription_expires_at:%d.%m.%Y}."


async def _cmd_suspend(session, op_id, target, args) -> str:
    from app.services.billing_admin import set_suspended  # noqa: PLC0415

    agency = await set_suspended(session, await _agency(session, target), True, f"operator:{op_id}")
    return f"{agency.name}: кабинет заблокирован, сбор остановлен."


async def _cmd_unsuspend(session, op_id, target, args) -> str:
    from app.services.billing_admin import set_suspended  # noqa: PLC0415

    agency = await set_suspended(session, await _agency(session, target), False, f"operator:{op_id}")
    return f"{agency.name}: кабинет снова доступен."
