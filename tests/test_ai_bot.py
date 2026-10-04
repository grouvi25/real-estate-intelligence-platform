"""ТЗ «AI-бот продажник» v1: public replies, the DM, consent, learning."""
import os
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services import bot_conversation, bot_reply_engine

db_only = pytest.mark.skipif(os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL")


def test_the_plan_caps_the_mode():
    agency = SimpleNamespace(bot_mode="auto")
    assert bot_reply_engine.effective_mode(agency, SimpleNamespace(bot_mode_allowed="assist")) == "assist"
    assert bot_reply_engine.effective_mode(agency, None) == "auto"  # agencies before plans
    assert bot_reply_engine.effective_mode(SimpleNamespace(bot_mode="weird"), None) == "disabled"


def test_tone_rotation():
    agency = SimpleNamespace(bot_tone_ab_test="rotating")
    tones = {bot_reply_engine.pick_tone(agency, datetime(2026, 10, 1, h, tzinfo=timezone.utc)) for h in range(3)}
    assert tones == {"expert", "friendly", "concise"}
    assert bot_reply_engine.pick_tone(SimpleNamespace(bot_tone_ab_test="concise")) == "concise"


def test_examples_are_pairs_not_lone_questions():
    """The ТЗ pool stored only the buyer's messages with an empty reply, so the
    model had nothing to imitate. Examples without a reply are dropped."""
    from app.prompts.reply_generator import build_reply_prompt_with_examples

    prompt = build_reply_prompt_with_examples([
        {"user_message": "ищу 2к", "bot_reply": "В Геленджике 2к от 7 млн"},
        {"user_message": "одинокий вопрос", "bot_reply": ""}], "friendly")
    assert "В Геленджике 2к от 7 млн" in prompt and "одинокий вопрос" not in prompt
    assert "дружелюбный" in prompt


@pytest.mark.parametrize("value,budget", [("8 млн", 8_000_000), ("до 7,5 млн", 7_500_000),
                                          ("5-7 млн", 7_000_000), ("6000000", 6_000_000),
                                          ("900 тыс", 900_000), ("50 тыс", None), (None, None)])
def test_budget_parsing(value, budget):
    from app.services.lead_from_bot import parse_budget

    assert parse_budget(value) == budget


def test_stop_and_escalation_need_no_ai():
    assert bot_conversation.STOP_WORDS.search("Стоп, не интересно")
    assert bot_conversation.ESCALATION_WORDS.search("позовите живого человека пожалуйста")
    assert not bot_conversation.STOP_WORDS.search("стоимость квартир")


def test_bot_rules_are_in_the_dialogue_prompt():
    from app.prompts.bot_dm import SYSTEM_PROMPT_BOT_QUALIFICATION

    assert "ты бот?" in SYSTEM_PROMPT_BOT_QUALIFICATION
    assert "Не называй точные цены" in SYSTEM_PROMPT_BOT_QUALIFICATION


# ------------------------------------------------------------------ database

@pytest.fixture
def quiet(monkeypatch):
    """No Telegram, no AI, no Redis: recorded instead."""
    told, sent = [], []

    async def tell(agency, text):
        told.append(text)

    async def send(agency, user_id, text, buttons=None, platform="telegram"):
        sent.append((user_id, text, [b.callback_data for b in buttons or []], platform))
        return True

    async def daily(agency_id, increment=False):
        return 0

    monkeypatch.setattr(bot_reply_engine, "_tell_managers", tell)
    monkeypatch.setattr(bot_reply_engine, "_daily", daily)
    monkeypatch.setattr(bot_conversation, "_send", send)
    return SimpleNamespace(told=told, sent=sent)


async def _setup(mode="assist", plan="isolated", score=85):
    from tests.helpers import unique_telegram_id

    from app.database import async_session, run_migrations
    from app.models.agency import Agency
    from app.models.geo_location import GeoLocation
    from app.models.manager import Manager
    from app.models.signal import Signal

    await run_migrations()
    async with async_session() as s:
        agency = Agency(name="Бот-агентство", base_city="Геленджик", bot_mode=mode,
                        subscription_plan=plan, bot_reply_threshold=60)
        s.add(agency)
        await s.flush()
        geo = GeoLocation(agency_id=agency.id, city_name="Геленджик", geo_type="base")
        s.add(geo)
        s.add(Manager(agency_id=agency.id, name="Владелец", role="owner",
                      telegram_id=unique_telegram_id(), is_active=True))
        await s.flush()
        signal = Signal(agency_id=agency.id, geo_location_id=geo.id, raw_text="Куплю 2к в Геленджике до 8 млн",
                        intent_score=score, segment="family", status="new")
        s.add(signal)
        await s.commit()
        return agency.id, signal.id


@db_only
@pytest.mark.asyncio
async def test_assist_puts_a_draft_in_the_existing_queue(quiet, monkeypatch):
    from app.database import async_session, engine
    from app.models.bot import BotPublicReply
    from app.models.signal import Signal

    async def gen(session, agency, signal, tone):
        return "В Геленджике двушки у моря сейчас от 7 до 9 млн."

    monkeypatch.setattr(bot_reply_engine, "generate_reply", gen)
    try:
        _, signal_id = await _setup("assist")
        result = await bot_reply_engine.process_signal(str(signal_id))
        again = await bot_reply_engine.process_signal(str(signal_id))
        async with async_session() as s:
            signal = await s.get(Signal, signal_id)
            reply = await s.get(BotPublicReply, uuid.UUID(result["reply_id"]))
    finally:
        await engine.dispose()
    assert result["mode"] == "assist" and again == {"skipped": "already_replied"}
    assert signal.reply_status == "pending" and signal.reply_draft.startswith("В Геленджике двушки")
    assert reply.status == "draft" and quiet.told  # managers are told, nothing sent


@db_only
@pytest.mark.asyncio
async def test_what_keeps_the_bot_silent(quiet, monkeypatch):
    from app.database import engine

    async def gen(*a):
        raise AssertionError("must not be called")

    monkeypatch.setattr(bot_reply_engine, "generate_reply", gen)
    try:
        _, low = await _setup("auto", score=40)
        _, off = await _setup("disabled")
        assert await bot_reply_engine.process_signal(str(low)) == {"skipped": "below_threshold"}
        assert await bot_reply_engine.process_signal(str(off)) == {"skipped": "disabled"}
    finally:
        await engine.dispose()


@db_only
@pytest.mark.asyncio
async def test_a_failed_send_is_recorded_as_failed_not_sent(quiet, monkeypatch):
    from app.database import async_session, engine
    from app.models.bot import BotPublicReply
    from app.services import signal_bus

    async def gen(session, agency, signal, tone):
        return "Ответ"

    async def send(session, signal, manager_id=None):
        return {"sent": False, "reason": "chat not found"}

    monkeypatch.setattr(bot_reply_engine, "generate_reply", gen)
    monkeypatch.setattr(signal_bus, "send_signal_reply", send)
    try:
        _, signal_id = await _setup("auto")  # auto publishes at once
        result = await bot_reply_engine.process_signal(str(signal_id))
        async with async_session() as s:
            reply = await s.get(BotPublicReply, uuid.UUID(result["reply_id"]))
    finally:
        await engine.dispose()
    assert reply.status == "failed" and reply.fail_reason == "chat not found"


@db_only
@pytest.mark.asyncio
async def test_semi_auto_does_not_send_what_a_manager_dismissed(quiet, monkeypatch):
    from app.database import async_session, engine
    from app.models.bot import BotPublicReply
    from app.models.signal import Signal
    from worker.tasks import bot_tasks

    async def gen(session, agency, signal, tone):
        return "Ответ"

    monkeypatch.setattr(bot_reply_engine, "generate_reply", gen)
    monkeypatch.setattr(bot_tasks.publish_public_reply, "apply_async", lambda *a, **k: None)
    try:
        _, signal_id = await _setup("semi_auto")
        result = await bot_reply_engine.process_signal(str(signal_id))
        async with async_session() as s:
            (await s.get(Signal, signal_id)).reply_status = "dismissed"
            await s.commit()
        published = await bot_reply_engine.publish(result["reply_id"])
        async with async_session() as s:
            reply = await s.get(BotPublicReply, uuid.UUID(result["reply_id"]))
    finally:
        await engine.dispose()
    assert published["sent"] is False and reply.status == "rejected"


def _dm(user_id, text, username="buyer"):
    return {"chat": {"id": user_id, "type": "private"}, "text": text,
            "from": {"id": user_id, "username": username, "first_name": "Анна"}}


@db_only
@pytest.mark.asyncio
async def test_from_a_public_reply_to_a_consented_lead(quiet, monkeypatch):
    from sqlalchemy import select

    from tests.helpers import unique_telegram_id

    from app.database import async_session, engine
    from app.models.bot import BotConversation, BotPublicReply
    from app.models.lead import Lead
    from app.services import lead_from_bot

    followed = []
    monkeypatch.setattr(lead_from_bot, "queue_followups", lambda lead_id: followed.append(lead_id))
    answers = iter([
        {"greeting_text": "Здравствуйте! Я бот агентства. Что ищете?"},
        {"message_to_client": "Какой бюджет?", "collected_data": {"property_type": "квартира"}},
        {"message_to_client": "Понял, передам специалисту.", "collected_data": {"budget": "8 млн"},
         "is_qualification_complete": True},
    ])

    async def ai(*a, **k):
        return next(answers)

    monkeypatch.setattr(bot_conversation, "_ai_json", ai)
    buyer = unique_telegram_id()
    try:
        agency_id, signal_id = await _setup("assist")
        async with async_session() as s:
            reply = BotPublicReply(id=uuid.uuid4(), agency_id=agency_id, signal_id=signal_id,
                                   reply_text="Ответ", mode="assist", status="sent")
            s.add(reply)
            await s.commit()
        for text in (f"/start r_{reply.id.hex[:12]}", "Ищу квартиру у моря", "Бюджет 8 млн"):
            assert await bot_conversation.handle_message(_dm(buyer, text)) is True
        assert quiet.sent[-1][2] == ["consent:yes", "consent:no"]
        async with async_session() as s:
            assert (await s.execute(select(Lead).where(Lead.signal_id == signal_id))).first() is None
        await bot_conversation.handle_callback({"data": "consent:yes", "from": {"id": buyer}})
        async with async_session() as s:
            conv = (await s.execute(select(BotConversation).where(BotConversation.user_id == buyer))).scalar_one()
            lead = await s.get(Lead, conv.lead_id)
            reply = await s.get(BotPublicReply, reply.id)
    finally:
        await engine.dispose()
    assert conv.state == "qualified"
    assert (lead.source_type, lead.consent_given, lead.budget_max) == ("bot_dm", True, 8_000_000)
    assert lead.signal_id == signal_id and lead.telegram_username == "buyer"
    assert reply.got_response and reply.converted_to_lead
    assert followed == [str(lead.id)]


@db_only
@pytest.mark.asyncio
async def test_declining_or_stopping_erases_the_conversation(quiet, monkeypatch):
    from sqlalchemy import select

    from tests.helpers import unique_telegram_id

    from app.database import async_session, engine
    from app.models.bot import BotConversation

    async def ai(*a, **k):
        return {"greeting_text": "Привет", "message_to_client": "Бюджет?", "collected_data": {"budget": "5 млн"},
                "is_qualification_complete": True}

    monkeypatch.setattr(bot_conversation, "_ai_json", ai)
    decline, stop = unique_telegram_id(), unique_telegram_id()
    try:
        agency_id, _ = await _setup("assist")
        link = f"/start b_{agency_id.hex[:8]}"
        for user in (decline, stop):
            await bot_conversation.handle_message(_dm(user, link))
            await bot_conversation.handle_message(_dm(user, "Ищу дом, 5 млн"))
        await bot_conversation.handle_callback({"data": "consent:no", "from": {"id": decline}})
        await bot_conversation.handle_message(_dm(stop, "Стоп"))
        async with async_session() as s:
            convs = (await s.execute(select(BotConversation).where(
                BotConversation.user_id.in_([decline, stop])))).scalars().all()
    finally:
        await engine.dispose()
    assert {c.state for c in convs} == {"done"}  # over, not paused: no reminder follows
    assert all(c.history == [] and c.collected_data == {} and c.lead_id is None for c in convs)


@db_only
@pytest.mark.asyncio
async def test_managers_are_not_buyers_and_can_be_called(quiet, monkeypatch):
    from sqlalchemy import select

    from tests.helpers import unique_telegram_id

    from app.database import async_session, engine
    from app.models.bot import BotConversation
    from app.models.manager import Manager

    async def ai(*a, **k):
        return {"greeting_text": "Привет"}

    monkeypatch.setattr(bot_conversation, "_ai_json", ai)
    buyer = unique_telegram_id()
    try:
        agency_id, _ = await _setup("assist")
        async with async_session() as s:
            manager_tg = (await s.execute(select(Manager.telegram_id).where(
                Manager.agency_id == agency_id))).scalar_one()
        assert await bot_conversation.handle_message(_dm(manager_tg, f"/start b_{agency_id.hex[:8]}")) is False
        await bot_conversation.handle_message(_dm(buyer, f"/start b_{agency_id.hex[:8]}"))
        await bot_conversation.handle_message(_dm(buyer, "Соедините с менеджером"))
        async with async_session() as s:
            conv = (await s.execute(select(BotConversation).where(BotConversation.user_id == buyer))).scalar_one()
    finally:
        await engine.dispose()
    assert conv.state == "escalated" and any("живого специалиста" in t for t in quiet.told)


@db_only
@pytest.mark.asyncio
async def test_quiet_pauses_after_30_minutes_reminds_once_and_resumes(quiet, monkeypatch):
    """ТЗ 10: 30 minutes of silence -> silent; a reminder after 24 h; the next
    message from the person carries on where it stopped."""
    from tests.helpers import unique_telegram_id

    from app.database import async_session, engine
    from app.models.bot import BotConversation
    from worker.tasks.bot_tasks import _reminders, _timeouts

    async def ai(*a, **k):
        return {"message_to_client": "Какой район?", "collected_data": {}}

    monkeypatch.setattr(bot_conversation, "_ai_json", ai)
    user = unique_telegram_id()
    now = datetime.now(timezone.utc)
    try:
        agency_id, _ = await _setup("assist")
        async with async_session() as s:
            conv = BotConversation(agency_id=agency_id, user_platform="telegram", user_id=user,
                                   state="qualifying", collected_data={"budget": "7 млн"},
                                   history=[{"role": "user", "text": "ищу", "ts": now.isoformat()}],
                                   last_user_msg_at=now - timedelta(minutes=31))
            s.add(conv)
            await s.commit()
        assert await _timeouts(now) >= 1
        await _reminders(now)  # 31 minutes: too early for the reminder
        async with async_session() as s:
            assert (await s.get(BotConversation, conv.id)).reminded_at is None
        assert await _reminders(now + timedelta(hours=24)) >= 1
        async with async_session() as s:
            paused = await s.get(BotConversation, conv.id)
        assert paused.state == "silent" and paused.reminded_at is not None
        await bot_conversation.handle_message(_dm(user, "Центр, у моря"), str(agency_id))
        async with async_session() as s:
            resumed = await s.get(BotConversation, conv.id)
    finally:
        await engine.dispose()
    assert resumed.state == "qualifying" and resumed.collected_data["budget"] == "7 млн"


@db_only
@pytest.mark.asyncio
async def test_settings_respect_the_plan():
    from tests.helpers import unique_telegram_id

    from app.database import async_session, engine
    from app.dependencies import CurrentManager
    from app.exceptions import AppException
    from app.models.agency import Agency
    from app.models.manager import Manager
    from app.routers.bot import BotSettings, update_settings

    await __import__("app.database", fromlist=["x"]).run_migrations()
    try:
        async with async_session() as s:
            agency = Agency(name="Старт", base_city="Ейск", subscription_plan="start")
            s.add(agency)
            await s.flush()
            owner = Manager(agency_id=agency.id, name="В", role="owner", telegram_id=unique_telegram_id(),
                            is_active=True)
            s.add(owner)
            await s.commit()
        ctx = CurrentManager(str(owner.id), str(agency.id))
        async with async_session() as s:
            with pytest.raises(AppException) as err:
                await update_settings(BotSettings(bot_mode="auto"), current=ctx, session=s)
            assert err.value.code == "PLAN_LIMIT_BOT_MODE"
            ok = await update_settings(BotSettings(bot_mode="assist", bot_reply_threshold=70),
                                       current=ctx, session=s)
    finally:
        await engine.dispose()
    assert ok["effective_mode"] == "assist" and ok["max_mode"] == "assist"


@db_only
@pytest.mark.asyncio
async def test_the_same_dialogue_in_max(quiet, monkeypatch):
    """ТЗ: MAX through the same bot layer. A MAX bot_started with the agency's
    payload, a message, the consent callback -- and a lead from MAX."""
    from sqlalchemy import select

    from app.database import async_session, engine
    from app.models.bot import BotConversation
    from app.models.lead import Lead
    from app.routers.webhooks import handle_max_event
    from app.services import lead_from_bot
    from app.services.bot_abstraction import _max_button, BotButton

    monkeypatch.setattr(lead_from_bot, "queue_followups", lambda lead_id: None)
    answers = iter([{"greeting_text": "Здравствуйте!"},
                    {"message_to_client": "Передаю специалисту", "collected_data": {"budget": "6 млн"},
                     "is_qualification_complete": True}])

    async def ai(*a, **k):
        return next(answers)

    monkeypatch.setattr(bot_conversation, "_ai_json", ai)
    max_user = 3 * 10 ** 12 + int(uuid.uuid4().int % 10 ** 9)
    try:
        agency_id, _ = await _setup("assist")
        assert await handle_max_event({"update_type": "bot_started", "user": {"user_id": max_user, "name": "Ира"},
                                       "payload": f"b_{agency_id.hex[:8]}"}) == "buyer"
        await handle_max_event({"update_type": "message_created", "message": {
            "sender": {"user_id": max_user, "name": "Ира"}, "body": {"text": "Ищу квартиру, 6 млн"}}})
        assert quiet.sent[-1][2:] == (["consent:yes", "consent:no"], "max")
        await handle_max_event({"update_type": "message_callback", "callback": {
            "callback_id": "cb1", "payload": "consent:yes", "user": {"user_id": max_user}}})
        async with async_session() as s:
            conv = (await s.execute(select(BotConversation).where(BotConversation.user_id == max_user))).scalar_one()
            lead = await s.get(Lead, conv.lead_id)
    finally:
        await engine.dispose()
    assert conv.user_platform == "max" and conv.state == "qualified"
    assert (lead.source_platform, lead.budget_max, lead.telegram_username) == ("max", 6_000_000, None)
    assert _max_button(BotButton(text="Да", callback_data="consent:yes")) == {
        "type": "callback", "text": "Да", "payload": "consent:yes"}
