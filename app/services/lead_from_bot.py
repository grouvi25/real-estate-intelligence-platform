"""A lead from a qualified bot conversation. ТЗ «AI-бот продажник» v1, 5.3.

Created only after «Согласен» (the caller guarantees it). The consent text says
exactly what was agreed to, as the manual and lead-magnet paths do. A person who
came from a public reply is tied to that signal, so the chain signal -> reply ->
lead -> deal stays whole; if the signal already has a lead, that lead is reused.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import select

from app.config import config

logger = structlog.get_logger()

CONSENT_TEXT = ("Пользователь Telegram нажал «Согласен» в чат-боте агентства на запрос согласия "
                "на обработку имени в Telegram и параметров поиска жилья для подбора объектов.")
URGENCY_WORDS = (("hot", ("срочно", "сейчас", "месяц", "1-3", "до конца года")),
                 ("cold", ("год", "не спешу", "присматриваюсь", "пока смотрю")))
GOAL_WORDS = (("invest", ("инвест", "сдавать", "вложен")), ("relocate", ("переезд", "переезжа")),
              ("children", ("дет", "сын", "дочь")), ("own", ("для себя", "жить", "семь")))


def parse_budget(value: Any) -> Optional[int]:
    """«8 млн», «до 7,5 млн», «6000000», «5-7 млн» -> the upper bound in roubles."""
    if value in (None, ""):
        return None
    text = str(value).lower().replace(" ", " ")
    numbers = [float(n.replace(",", ".")) for n in re.findall(r"\d+(?:[.,]\d+)?", text.replace(" ", ""))]
    if not numbers:
        return None
    top = max(numbers)
    if "млн" in text or "миллион" in text:
        top *= 1_000_000
    elif "тыс" in text or "т.р" in text:
        top *= 1_000
    elif top < 1000:  # «бюджет 8» in a flat chat means millions
        top *= 1_000_000
    return int(top) if top >= 100_000 else None


def _pick(text: Any, table) -> Optional[str]:
    low = str(text or "").lower()
    for value, words in table:
        if any(w in low for w in words):
            return value
    return None


async def create_lead_from_conversation(session, agency, conv):
    from app.models.bot import BotPublicReply  # noqa: PLC0415
    from app.models.geo_location import GeoLocation  # noqa: PLC0415
    from app.models.lead import Lead  # noqa: PLC0415
    from app.models.signal import Signal  # noqa: PLC0415

    data = conv.collected_data or {}
    lead = None
    if conv.signal_id:
        lead = (await session.execute(select(Lead).where(Lead.signal_id == conv.signal_id))).scalars().first()
    created = lead is None
    if lead is None:
        signal = await session.get(Signal, conv.signal_id) if conv.signal_id else None
        geo_id = signal.geo_location_id if signal is not None else await session.scalar(
            select(GeoLocation.id).where(GeoLocation.agency_id == agency.id)
            .order_by(GeoLocation.geo_type.asc(), GeoLocation.created_at).limit(1))
        lead = Lead(
            agency_id=agency.id, geo_location_id=geo_id,
            signal_id=conv.signal_id, source_signal_id=conv.signal_id,
            source_type="bot_dm", source_platform=conv.user_platform,
            segment=signal.segment if signal is not None else None,
            intent_score=signal.intent_score if signal is not None else None,
            budget_max=parse_budget(data.get("budget")),
            purchase_goal=_pick(data.get("goal"), GOAL_WORDS),
            urgency=_pick(data.get("timeline"), URGENCY_WORDS) or "warm",
            status="new",
            telegram_username=conv.username if conv.user_platform == "telegram" else None,
            consent_given=True, consent_given_at=datetime.now(timezone.utc),
            consent_text=CONSENT_TEXT, consent_version=config.consent_version,
        )
        if conv.display_name:
            lead.name = conv.display_name
        session.add(lead)
    lead.buyer_profile = {
        **(lead.buyer_profile or {}),
        "collected_via": "bot_qualification", "bot_conversation_id": str(conv.id),
        **{k: v for k, v in data.items() if k in ("budget", "goal", "timeline", "property_type",
                                                   "district", "mortgage") and v},
    }
    if conv.signal_id:
        reply = (await session.execute(select(BotPublicReply).where(
            BotPublicReply.signal_id == conv.signal_id))).scalars().first()
        if reply is not None:
            reply.converted_to_lead = True
    await session.flush()

    lead._created_by_bot = created  # the caller queues follow-ups after its commit
    logger.info("Lead from bot conversation", lead_id=str(lead.id), created=created)
    return lead


def queue_followups(lead_id: str) -> None:
    """Matching and the TopNLab push for a new bot lead, once it is committed."""
    try:
        from worker.tasks.matching_tasks import run_matching_for_lead  # noqa: PLC0415
        from worker.tasks.topnlab_sync import queue_topnlab_sync  # noqa: PLC0415

        run_matching_for_lead.delay(lead_id)
        queue_topnlab_sync(lead_id)
    except Exception as e:  # noqa: BLE001 - the lead is what matters; matching can rerun
        logger.error("Follow-up for a bot lead not queued", lead_id=lead_id, error=str(e)[:200])
