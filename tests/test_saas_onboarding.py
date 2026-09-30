"""ТЗ «SaaS-слой» v1, разделы 5-7: sales bot, operator, ЮKassa, reminders, public API."""
import os
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

db_only = pytest.mark.skipif(os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL")
OPERATOR_ID = 555000111


def test_city_names_compare_whole_and_normalized():
    from app.services.onboarding import normalize_city

    assert normalize_city(" г. Геленджик ") == normalize_city("геленджик")
    assert normalize_city("Сочи") != normalize_city("Сочи-Адлер")
    assert normalize_city("Орёл") == normalize_city("Орел")


@pytest.mark.parametrize("raw,phone", [("+7 (918) 123-45-67", "79181234567"),
                                       ("89181234567", "79181234567"),
                                       ("9181234567", "79181234567"), ("12345", None)])
def test_phone_parsing(raw, phone):
    from app.services.sales_bot import _phone

    assert _phone(raw) == phone


# ------------------------------------------------------------- operator auth

@pytest.mark.asyncio
async def test_operator_token_is_not_a_manager_token_and_back(monkeypatch):
    from app.config import config
    from app.dependencies import create_operator_token, get_current_manager, get_platform_operator
    from app.exceptions import AppException
    from app.security import create_access_token

    monkeypatch.setattr(config, "platform_operator_ids_raw", str(OPERATOR_ID))
    op_token = create_operator_token(OPERATOR_ID)
    assert await get_platform_operator(f"Bearer {op_token}") == OPERATOR_ID
    with pytest.raises(AppException):
        await get_current_manager(f"Bearer {op_token}")  # no agency in it
    manager_token = create_access_token(str(uuid.uuid4()), agency_id=str(uuid.uuid4()))
    with pytest.raises(AppException) as err:
        await get_platform_operator(f"Bearer {manager_token}")
    assert err.value.code == "OPERATOR_ONLY"
    with pytest.raises(AppException) as err:
        await get_platform_operator(None)
    assert err.value.status_code == 401


# ------------------------------------------------------------------ ЮKassa

def _request(**kw):
    base = dict(id=uuid.uuid4(), plan_id="start", status="payment_pending", payment_id=None)
    base.update(kw)
    return SimpleNamespace(**base)


class _Session:
    def __init__(self, request, plan_price=250000, existing=None):
        self.request, self.added, self.commits = request, [], 0
        self.plan = SimpleNamespace(id="start", one_time_price=plan_price)
        self.existing = existing

    async def get(self, model, key):
        return self.plan if model.__name__ == "SubscriptionPlan" else self.request

    async def scalar(self, stmt):
        return self.existing

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1


def _paid(request, value="250000.00", status="succeeded"):
    return {"id": "pay-1", "status": status, "paid": status == "succeeded",
            "amount": {"value": value, "currency": "RUB"},
            "metadata": {"request_id": str(request.id)}}


@pytest.mark.asyncio
async def test_a_forged_notification_pays_nothing(monkeypatch):
    from app.services import yookassa

    req = _request()

    async def fetch(pid):
        return _paid(req, status="pending")  # what ЮKassa really says

    monkeypatch.setattr(yookassa, "fetch_payment", fetch)
    body = {"event": "payment.succeeded", "object": {"id": "pay-1", "status": "succeeded"}}
    assert await yookassa.handle_notification(_Session(req), body) is None
    assert req.status == "payment_pending"


@pytest.mark.asyncio
async def test_a_real_payment_counts_once_and_only_in_full(monkeypatch):
    from app.services import yookassa

    req = _request()
    answer = {"payment": _paid(req)}

    async def fetch(pid):
        return answer["payment"]

    monkeypatch.setattr(yookassa, "fetch_payment", fetch)
    body = {"event": "payment.succeeded", "object": {"id": "pay-1"}}

    short = _request()
    answer["payment"] = _paid(short, value="1000.00")
    assert await yookassa.handle_notification(_Session(short), body) is None

    answer["payment"] = _paid(req)
    session = _Session(req)
    assert await yookassa.handle_notification(session, body) == str(req.id)
    assert req.status == "paid" and req.payment_id == "pay-1"
    assert session.added[0].payment_id == "pay-1" and session.added[0].amount_rub == 250000

    again = _Session(req, existing=uuid.uuid4())
    assert await yookassa.handle_notification(again, body) is None and not again.added


# ------------------------------------------------------------- live database

@pytest.fixture
def outbox(monkeypatch):
    """Everything the sales bot says, instead of Telegram."""
    from app.services import sales_bot

    sent = []

    async def send(chat_id, text, reply_markup=None):
        sent.append((chat_id, text))
        return True

    async def notify(text):
        sent.append(("operators", text))

    monkeypatch.setattr(sales_bot, "send", send)
    monkeypatch.setattr(sales_bot, "notify_operators", notify)
    return sent


def _msg(uid, text=None, contact=None):
    msg = {"from": {"id": uid, "username": "boss", "first_name": "Олег"},
           "chat": {"id": uid, "type": "private"}}
    if text is not None:
        msg["text"] = text
    if contact is not None:
        msg["contact"] = contact
    return {"update_id": 1, "message": msg}


@db_only
@pytest.mark.asyncio
async def test_from_start_to_a_working_agency(outbox, monkeypatch):
    """The whole sales path: prospect -> request -> approve -> paid -> agency."""
    from sqlalchemy import select

    from tests.helpers import unique_telegram_id

    import worker.tasks.geo_tasks as geo_tasks
    from app.config import config
    from app.database import async_session, engine, run_migrations
    from app.models.agency import Agency
    from app.models.billing import OnboardingRequest
    from app.models.manager import Manager
    from app.services import sales_bot

    monkeypatch.setattr(config, "platform_operator_ids_raw", str(OPERATOR_ID))
    monkeypatch.setattr(config, "yookassa_shop_id", None)
    monkeypatch.setattr(geo_tasks.generate_keywords_for_geo, "delay", lambda *a, **k: None)
    await run_migrations()
    city = "Туапсе-" + uuid.uuid4().hex[:6]
    prospect = unique_telegram_id()
    try:
        for step in (_msg(prospect, "/start"), _msg(prospect, city), _msg(prospect, "Туапсе Дом"),
                     _msg(prospect, contact={"phone_number": "+7 918 555-44-33"})):
            await sales_bot.handle_update(step)
        async with async_session() as s:
            req = (await s.execute(select(OnboardingRequest).where(
                OnboardingRequest.telegram_id == prospect))).scalar_one()
            raw_phone = bytes(req._phone_encrypted)
            assert req.phone == "79185554433" and b"79185554433" not in raw_phone
        rid = str(req.id)[:8]
        assert any(t == "operators" and f"/approve_{rid}" in x for t, x in outbox)

        # «Выделенный»: a plan name the schema from 001 did not allow at all.
        for command in (f"/approve_{rid} isolated", f"/paid_{rid}", f"/create_{rid}"):
            await sales_bot.handle_update(_msg(OPERATOR_ID, command))

        async with async_session() as s:
            req = await s.get(OnboardingRequest, req.id)
            agency = await s.get(Agency, req.agency_id)
            owner = (await s.execute(select(Manager).where(Manager.telegram_id == prospect))).scalar_one()
        assert req.status == "completed"
        assert (agency.subscription_plan, agency.max_managers, agency.max_cities) == ("isolated", 20, 5)
        assert agency.subscription_expires_at > datetime.now(timezone.utc) + timedelta(days=29)
        assert owner.role == "owner" and owner.agency_id == agency.id
        invite = [x for t, x in outbox if t == prospect and "inv_" in x]
        assert invite and agency.invite_token in invite[0]

        # The city is now taken for the next prospect.
        other = unique_telegram_id()
        await sales_bot.handle_update(_msg(other, "/start"))
        await sales_bot.handle_update(_msg(other, city))
        assert "уже подключён" in outbox[-1][1]

        await sales_bot.handle_update(_msg(OPERATOR_ID, f"/extend_{str(agency.id)[:8]} 2"))
        async with async_session() as s:
            agency = await s.get(Agency, agency.id)
        assert agency.subscription_expires_at > datetime.now(timezone.utc) + timedelta(days=89)
    finally:
        await engine.dispose()


@db_only
@pytest.mark.asyncio
async def test_a_stranger_cannot_use_operator_commands(outbox):
    from tests.helpers import unique_telegram_id

    from app.database import engine
    from app.services import sales_bot

    stranger = unique_telegram_id()
    try:
        await sales_bot.handle_update(_msg(stranger, "/requests"))
    finally:
        await engine.dispose()
    assert outbox and outbox[-1][0] == stranger
    assert "REIP" in outbox[-1][1]  # the greeting, not the request list


@db_only
@pytest.mark.asyncio
async def test_operator_api_and_the_closed_geo_path(monkeypatch):
    from fastapi.testclient import TestClient

    from app.config import config
    from app.database import engine
    from app.dependencies import create_operator_token
    from app.main import app
    from app.security import create_access_token

    monkeypatch.setattr(config, "platform_operator_ids_raw", str(OPERATOR_ID))
    try:
        client = TestClient(app)
        op = {"Authorization": f"Bearer {create_operator_token(OPERATOR_ID)}"}
        dash = client.get("/api/operator/dashboard", headers=op)
        assert dash.status_code == 200 and "total_agencies" in dash.json()
        manager = {"Authorization": "Bearer " + create_access_token(str(uuid.uuid4()),
                                                                    agency_id=str(uuid.uuid4()))}
        assert client.get("/api/operator/dashboard", headers=manager).status_code == 403
        geo = client.post(f"/api/geo/agencies/{uuid.uuid4()}/geo",
                          json={"city_name": "Где-то", "region": "Там"})
        assert geo.status_code == 401
        check = client.get("/api/platform/city-check", params={"city": "Нигде-" + uuid.uuid4().hex[:6]})
        assert check.status_code == 200 and check.json()["available"] is True
        assert client.post("/api/webhooks/sales", json={}).status_code == 403
    finally:
        await engine.dispose()


@db_only
@pytest.mark.asyncio
async def test_daily_check_reminds_and_suspends(monkeypatch, outbox):
    from tests.helpers import unique_telegram_id

    from app.config import config
    from app.database import async_session, engine, run_migrations
    from app.models.agency import Agency
    from app.models.manager import Manager
    from app.services import billing_admin
    from app.services.bot_abstraction import bot_layer

    told = []

    async def notify(manager_id, text):
        told.append(text)
        return True

    monkeypatch.setattr(bot_layer, "notify_manager", notify)
    monkeypatch.setattr(config, "platform_reminder_days_raw", "7,3,1")
    now = datetime.now(timezone.utc)
    await run_migrations()
    try:
        async with async_session() as s:
            soon = Agency(name="Скоро-" + uuid.uuid4().hex[:4], base_city="Ейск",
                          subscription_expires_at=now + timedelta(days=3, hours=1))
            gone = Agency(name="Всё-" + uuid.uuid4().hex[:4], base_city="Ейск",
                          subscription_expires_at=now - timedelta(days=20))
            s.add_all([soon, gone])
            await s.flush()
            s.add(Manager(agency_id=soon.id, name="В", role="owner",
                          telegram_id=unique_telegram_id(), is_active=True))
            await s.commit()
        stats = await billing_admin.check_subscriptions(now)
        async with async_session() as s:
            gone = await s.get(Agency, gone.id)
    finally:
        await engine.dispose()
    assert stats["reminded"] >= 1 and any("через 3 дня" in t for t in told)
    assert gone.subscription_active is False
    assert any(t == "operators" and gone.name in x for t, x in outbox)
