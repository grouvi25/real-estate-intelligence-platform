"""The AI sales bot in a buyer's DM. ТЗ «AI-бот продажник» v1, разделы 1.2, 5.1, 5.3, 9.

greeting -> qualifying -> consent_pending -> qualified (lead created)
                        \\-> escalated (a manager takes over)      \\-> done (declined)
"stop" at any point -> done: the conversation is over, the bot says nothing more.
BOT_CONVERSATION_TIMEOUT_MINUTES of silence -> silent: the bot stops asking;
after BOT_REMINDER_HOURS one reminder; any message from the person resumes it.

Who the person is talking to: an agency's own bot, or the platform bot opened
through a link from a public reply (/start r_<reply>) or an agency link
(/start b_<agency>). A manager writing to the platform bot is never a buyer.

152-ФЗ (ТЗ 9.1): no lead exists until the person presses «Согласен»; the bot
never asks for a phone, a full name or documents; declining consent or "stop"
erases the conversation history; the lead keeps the Telegram name only.

Consent and stop are recognised without the model: a button press is a button
press, and "stop" must work even when the AI is down.
"""
from __future__ import annotations

import html
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import select

from app.config import config

logger = structlog.get_logger()

HISTORY_LIMIT = 20
MESSAGE_LIMIT = 500
# silent is paused, not over: a message from the person picks the dialogue up again.
OPEN_STATES = ("greeting", "qualifying", "consent_pending", "escalated", "silent")
STOP_WORDS = re.compile(r"^\s*(стоп|stop|хватит|не пишите|не интересно|отписаться|/stop)\b", re.I)
ESCALATION_WORDS = re.compile(
    r"(менеджер|риелтор|риэлтор|специалист|живой человек|живого человека|позвоните|перезвоните|"
    r"соедините|хочу поговорить с)", re.I)
CONSENT_YES, CONSENT_NO = "consent:yes", "consent:no"


# ---------------------------------------------------------------- plumbing

def _history(conv, role: str, text: str) -> None:
    items = list(conv.history or [])
    items.append({"role": role, "text": (text or "")[:MESSAGE_LIMIT],
                  "ts": datetime.now(timezone.utc).isoformat()})
    conv.history = items[-HISTORY_LIMIT:]


async def _send(agency, user_id: int, text: str, buttons=None, platform: str = "telegram") -> bool:
    """Through the agency's own Telegram bot if it has one; MAX has one platform bot."""
    from app.services.bot_abstraction import BotMessage, BotPlatform, bot_layer  # noqa: PLC0415

    token = agency.telegram_bot_token if agency is not None and platform == "telegram" else None
    return await bot_layer.send_message(
        user_id, BotPlatform(platform), BotMessage(text=text, buttons=buttons), token)


async def _ai_json(system: str, user: str, module: str, agency_id: str, fallback: dict) -> dict:
    from app.services.ai_service import AIService, safe_ai_parse  # noqa: PLC0415

    ai = AIService()
    try:
        return safe_ai_parse(await ai.complete(system, user, module, agency_id=agency_id), fallback)
    except Exception as e:  # noqa: BLE001 - the conversation survives an AI outage
        logger.warning("Bot AI call failed", module=module, error=str(e)[:200])
        return fallback
    finally:
        await ai.close()


async def _open_conversation(session, agency_id, user_id: int, platform: str = "telegram"):
    from app.models.bot import BotConversation  # noqa: PLC0415

    q = select(BotConversation).where(
        BotConversation.user_platform == platform, BotConversation.user_id == user_id,
        BotConversation.state.in_(OPEN_STATES))
    if agency_id is not None:
        q = q.where(BotConversation.agency_id == agency_id)
    return (await session.execute(q.order_by(BotConversation.updated_at.desc()).limit(1))).scalars().first()


async def _is_manager(session, user_id: int, platform: str = "telegram") -> bool:
    from app.models.manager import Manager  # noqa: PLC0415

    column = Manager.telegram_id if platform == "telegram" else Manager.max_user_id
    return bool(await session.scalar(select(Manager.id).where(column == user_id)))


async def _agency_from_payload(session, payload: Optional[str]):
    """(agency, reply) named by a start payload, or (None, None)."""
    from sqlalchemy import Text, func  # noqa: PLC0415

    from app.models.agency import Agency  # noqa: PLC0415
    from app.models.bot import BotPublicReply  # noqa: PLC0415

    payload = (payload or "").strip().lower()
    if re.fullmatch(r"r_[0-9a-f]{12}", payload):
        reply = (await session.execute(select(BotPublicReply).where(
            func.replace(func.cast(BotPublicReply.id, Text), "-", "").startswith(payload[2:])))).scalars().first()
        if reply is not None:
            return await session.get(Agency, reply.agency_id), reply
    if re.fullmatch(r"b_[0-9a-f]{8,32}", payload):
        agency = (await session.execute(select(Agency).where(
            func.replace(func.cast(Agency.id, Text), "-", "").startswith(payload[2:])))).scalars().first()
        return agency, None
    return None, None


# ------------------------------------------------------------- entry points

async def handle_message(message: dict[str, Any], bot_agency_id: Optional[str] = None,
                         platform: str = "telegram") -> bool:
    """A private message to a bot. Returns True if it was a buyer's and is handled
    here; False leaves it to the cabinet handler (/start for managers etc.)."""
    from app.database import async_session  # noqa: PLC0415
    from app.models.agency import Agency  # noqa: PLC0415
    from app.models.bot import BotConversation  # noqa: PLC0415
    from app.routers.webhooks import start_payload  # noqa: PLC0415

    chat = message.get("chat") or {}
    user = message.get("from") or {}
    user_id = user.get("id") or chat.get("id")
    text = (message.get("text") or "").strip()
    if not user_id or chat.get("type", "private") != "private" or not text:
        return False
    payload = start_payload(text) if text.startswith("/start") else None
    if payload and payload.startswith("inv_"):
        return False  # a manager's invitation, not a buyer

    async with async_session() as session:
        if await _is_manager(session, int(user_id), platform):
            return False
        agency, reply = await _agency_from_payload(session, payload)
        if agency is None and bot_agency_id:
            agency = await session.get(Agency, uuid.UUID(str(bot_agency_id)))
        conv = await _open_conversation(session, agency.id if agency else None, int(user_id), platform)
        if conv is not None and agency is None:
            agency = await session.get(Agency, conv.agency_id)
        if agency is None or agency.bot_mode == "disabled":
            return False
        if conv is None:
            if not text.startswith("/start") and not bot_agency_id:
                return False  # a stray message to the platform bot
            conv = BotConversation(
                agency_id=agency.id, user_platform=platform, user_id=int(user_id),
                username=user.get("username"), display_name=user.get("first_name"),
                state="greeting", history=[], collected_data={}, bot_mode=agency.bot_mode,
                tone_variant=agency.bot_tone_ab_test if agency.bot_tone_ab_test != "rotating" else "expert",
                signal_id=reply.signal_id if reply else None)
            session.add(conv)
            if reply is not None:
                reply.got_response = True
            await session.flush()
        conv.last_user_msg_at = datetime.now(timezone.utc)
        await _step(session, agency, conv, "" if text.startswith("/start") else text)
        await session.commit()
    return True


async def handle_callback(callback: dict[str, Any], bot_agency_id: Optional[str] = None,
                          platform: str = "telegram") -> bool:
    """«Согласен» / «Не согласен» under the consent request."""
    from app.database import async_session  # noqa: PLC0415
    from app.models.agency import Agency  # noqa: PLC0415

    data = callback.get("data") or ""
    user_id = (callback.get("from") or {}).get("id")
    if data not in (CONSENT_YES, CONSENT_NO) or not user_id:
        return False
    async with async_session() as session:
        agency_id = uuid.UUID(str(bot_agency_id)) if bot_agency_id else None
        conv = await _open_conversation(session, agency_id, int(user_id), platform)
        if conv is None or conv.state != "consent_pending":
            return True  # a stale button: nothing to do, but it was ours
        agency = await session.get(Agency, conv.agency_id)
        new_lead = None
        if data == CONSENT_YES:
            new_lead = await _consent_given(session, agency, conv)
        else:
            conv.state, conv.history, conv.collected_data = "done", [], {}
            await _send(agency, conv.user_id, platform=conv.user_platform, text=_texts().CONSENT_NO)
        await session.commit()
    if new_lead is not None:
        from app.services.lead_from_bot import queue_followups  # noqa: PLC0415

        queue_followups(str(new_lead))
    return True


def _texts():
    from app.prompts import bot_dm  # noqa: PLC0415

    return bot_dm


# ------------------------------------------------------------- the dialogue

async def _step(session, agency, conv, text: str) -> None:
    from app.prompts.qualification import USER_PROMPT_QUALIFICATION  # noqa: PLC0415

    t = _texts()
    if text and STOP_WORDS.search(text):
        conv.state, conv.history, conv.collected_data = "done", [], {}
        await _send(agency, conv.user_id, platform=conv.user_platform, text=t.STOP_MESSAGE)
        return
    if conv.state == "silent":
        conv.state = "qualifying" if conv.history else "greeting"  # they are back
    if text and ESCALATION_WORDS.search(text):
        await _escalate(session, agency, conv, text)
        return
    if conv.state == "escalated":
        _history(conv, "user", text)
        return  # a manager is on it; the bot does not talk over them
    if conv.state == "greeting":
        greeting = (await _ai_json(
            t.SYSTEM_PROMPT_BOT_GREETING.format(agency_name=agency.name, city=agency.base_city),
            "Начало диалога", "qualification", str(agency.id), {}
        )).get("greeting_text") or t.GREETING_FALLBACK.format(agency_name=agency.name)
        conv.state = "qualifying"
        if text:
            _history(conv, "user", text)
        _history(conv, "bot", greeting)
        await _send(agency, conv.user_id, platform=conv.user_platform, text=html.escape(greeting))
        return
    if conv.state == "consent_pending":
        await _ask_consent(agency, conv, None)
        return
    _history(conv, "user", text)
    result = await _ai_json(
        t.SYSTEM_PROMPT_BOT_QUALIFICATION,
        USER_PROMPT_QUALIFICATION.format(
            agency_name=agency.name, city=agency.base_city,
            conversation_history=json.dumps(conv.history[-10:], ensure_ascii=False),
            last_message=text, collected_data=json.dumps(conv.collected_data or {}, ensure_ascii=False)),
        "qualification", str(agency.id),
        {"message_to_client": t.FALLBACK_REPLY, "collected_data": {}, "is_qualification_complete": False})
    fresh = {k: v for k, v in (result.get("collected_data") or {}).items() if v not in (None, "", [])}
    conv.collected_data = {**(conv.collected_data or {}), **fresh}
    answer = str(result.get("message_to_client") or t.FALLBACK_REPLY)
    user_turns = sum(1 for h in conv.history if h.get("role") == "user")
    if result.get("is_qualification_complete") or result.get("ready_to_transfer") or user_turns >= 6:
        await _ask_consent(agency, conv, answer)
        return
    _history(conv, "bot", answer)
    await _send(agency, conv.user_id, platform=conv.user_platform, text=html.escape(answer))


async def _ask_consent(agency, conv, summary: Optional[str]) -> None:
    from app.services.bot_abstraction import BotButton  # noqa: PLC0415

    t = _texts()
    privacy = f"\nПолитика конфиденциальности: {config.base_url.rstrip('/')}/privacy"
    text = (html.escape(summary) + "\n\n" if summary else "") + t.CONSENT_REQUEST.format(privacy=privacy)
    conv.state = "consent_pending"
    _history(conv, "bot", "[запрос согласия]")
    await _send(agency, conv.user_id, platform=conv.user_platform, text=text,
                buttons=[BotButton(text="Согласен", callback_data=CONSENT_YES),
                         BotButton(text="Не согласен", callback_data=CONSENT_NO)])


async def _consent_given(session, agency, conv) -> None:
    from app.services.lead_from_bot import create_lead_from_conversation  # noqa: PLC0415

    lead = await create_lead_from_conversation(session, agency, conv)
    conv.lead_id, conv.state = lead.id, "qualified"
    await _send(agency, conv.user_id, platform=conv.user_platform, text=_texts().CONSENT_YES)
    from app.services.bot_reply_engine import _tell_managers  # noqa: PLC0415

    who = f"@{conv.username}" if conv.username else (conv.display_name or "без имени")
    await _tell_managers(agency, f"ИИ-бот квалифицировал покупателя {who}: {_summary(conv.collected_data)}. "
                                 "Лид — в разделе «Лиды».")
    return lead.id if getattr(lead, "_created_by_bot", False) else None


async def _escalate(session, agency, conv, text: str) -> None:
    from app.services.bot_reply_engine import _tell_managers  # noqa: PLC0415

    _history(conv, "user", text)
    conv.state = "escalated"
    # No manager contact in the answer: managers are known by Telegram id, not
    # by a public handle, so the manager writes first.
    await _send(agency, conv.user_id, platform=conv.user_platform, text=_texts().ESCALATION_MESSAGE.format(contact=""))
    who = f"@{conv.username}" if conv.username else f"id {conv.user_id}"
    await _tell_managers(agency, f"Покупатель {who} просит живого специалиста. Собрано: "
                                 f"{_summary(conv.collected_data)}. Последнее: «{text[:200]}»")


LABELS = {"budget": "бюджет", "goal": "цель", "timeline": "срок", "property_type": "тип",
          "district": "район", "mortgage": "ипотека"}


def _summary(data: dict) -> str:
    parts = [f"{label} — {data[key]}" for key, label in LABELS.items() if data and data.get(key)]
    return ", ".join(parts) or "параметры ещё не собраны"
