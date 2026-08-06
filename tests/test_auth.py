"""Tests for platform auth: Telegram WebApp signature + /auth/platform endpoint."""
import hashlib
import hmac
import json
import os
import secrets
import time
from urllib.parse import urlencode

import pytest

from app.config import config
from app.routers.auth import (
    AuthRequest,
    verify_max_init_data,
    verify_telegram_init_data,
)


def build_tg_init_data(bot_token: str, user: dict, auth_date: int | None = None) -> str:
    """Build a correctly-signed Telegram WebApp initData string (WebApp algorithm)."""
    auth_date = auth_date if auth_date is not None else int(time.time())
    params = {
        "auth_date": str(auth_date),
        "query_id": "AAF_test",
        "user": json.dumps(user, ensure_ascii=False, separators=(",", ":")),
    }
    data_check_string = "\n".join(f"{k}={params[k]}" for k in sorted(params))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    params["hash"] = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(params)


# --- unit tests (no DB) ---

def test_verify_telegram_valid():
    init_data = build_tg_init_data(config.telegram_bot_token, {"id": 555, "first_name": "Иван"})
    user = verify_telegram_init_data(init_data)
    assert user is not None
    assert user["id"] == 555
    assert user["first_name"] == "Иван"


def test_verify_telegram_bad_hash():
    init_data = build_tg_init_data(config.telegram_bot_token, {"id": 1})
    tampered = init_data[:-4] + ("0000" if not init_data.endswith("0000") else "1111")
    assert verify_telegram_init_data(tampered) is None


def test_verify_telegram_missing_hash():
    assert verify_telegram_init_data("auth_date=123&user=%7B%7D") is None


def test_verify_telegram_expired():
    old = int(time.time()) - 48 * 60 * 60
    init_data = build_tg_init_data(config.telegram_bot_token, {"id": 2}, auth_date=old)
    assert verify_telegram_init_data(init_data) is None


def test_verify_telegram_wrong_token():
    # Signed with a different token -> must fail against the configured one.
    init_data = build_tg_init_data("999:OTHER", {"id": 3})
    assert verify_telegram_init_data(init_data) is None


def test_verify_max_rejects_unsigned_init_data():
    """MAX used to accept a bare user dict in development and refuse everything in
    production. Now the signature is checked on both -- see tests/test_max_platform.py
    for the full contract."""
    user = verify_max_init_data(urlencode({"user": json.dumps({"id": 77, "first_name": "M"})}))
    assert user is None


# --- integration test (needs PostgreSQL) ---

pytestmark_db = pytest.mark.skipif(
    os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL"
)


@pytestmark_db
@pytest.mark.asyncio
async def test_auth_platform_creates_and_reuses_manager(monkeypatch):
    from app.database import async_session, engine, run_migrations
    from app.models.agency import Agency
    from app.routers.auth import auth_platform
    from app.security import decode_access_token

    await run_migrations()
    try:
        async with async_session() as s:
            agency = Agency(name="Owner Agency", base_city="Геленджик",
                            invite_token=secrets.token_hex(8))
            s.add(agency)
            await s.commit()
            await s.refresh(agency)
            agency_id, invite = str(agency.id), agency.invite_token

        monkeypatch.setattr(config, "platform_owner_agency_id", agency_id)
        tg_id = 700000 + int(time.time()) % 100000
        init_data = build_tg_init_data(config.telegram_bot_token, {"id": tg_id, "first_name": "Иван"})

        async with async_session() as s:
            resp1 = await auth_platform(
                AuthRequest(platform="telegram", init_data=init_data, invite=invite),
                session=s)
        payload = decode_access_token(resp1["token"])
        assert payload["agency_id"] == agency_id
        assert resp1["manager"]["role"] == "manager"
        manager_id = resp1["manager"]["id"]

        # Second login with same identity must reuse the manager, not duplicate.
        async with async_session() as s:
            resp2 = await auth_platform(
                AuthRequest(platform="telegram", init_data=init_data), session=s)
        assert resp2["manager"]["id"] == manager_id
    finally:
        await engine.dispose()


# --- joining an agency requires an invitation ---------------------------------

@pytestmark_db
@pytest.mark.asyncio
async def test_a_stranger_cannot_walk_into_the_cabinet(monkeypatch):
    """Any Telegram user who found the bot used to become a manager of
    PLATFORM_OWNER_AGENCY_ID and see that agency's signals, leads and their
    clients' personal data -- the data everything else encrypts."""
    from app.database import async_session, engine, run_migrations
    from app.exceptions import AppException
    from app.models.agency import Agency
    from app.routers.auth import auth_platform

    await run_migrations()
    try:
        async with async_session() as s:
            agency = Agency(name="Closed Agency", base_city="Геленджик",
                            invite_token=secrets.token_hex(8))
            s.add(agency)
            await s.commit()
            agency_id = str(agency.id)

        monkeypatch.setattr(config, "platform_owner_agency_id", agency_id)
        init_data = build_tg_init_data(
            config.telegram_bot_token,
            {"id": 810000 + int(time.time()) % 100000, "first_name": "Чужой"})

        async with async_session() as s:
            with pytest.raises(AppException) as err:
                await auth_platform(
                    AuthRequest(platform="telegram", init_data=init_data), session=s)
        assert err.value.status_code == 403
        assert err.value.code == "INVITE_REQUIRED"
    finally:
        await engine.dispose()


@pytestmark_db
@pytest.mark.asyncio
async def test_the_invite_decides_which_agency_you_join():
    """Not the platform owner's agency -- the one whose token the link carries."""
    from app.database import async_session, engine, run_migrations
    from app.models.agency import Agency
    from app.routers.auth import auth_platform

    await run_migrations()
    try:
        async with async_session() as s:
            other = Agency(name="Другое агентство", base_city="Анапа",
                           invite_token=secrets.token_hex(8))
            s.add(other)
            await s.commit()
            other_id, token = str(other.id), other.invite_token

        init_data = build_tg_init_data(
            config.telegram_bot_token,
            {"id": 820000 + int(time.time()) % 100000, "first_name": "Приглашённый"})

        async with async_session() as s:
            resp = await auth_platform(
                AuthRequest(platform="telegram", init_data=init_data, invite=f"inv_{token}"),
                session=s)
        assert resp["manager"]["agency_id"] == other_id
        assert resp["manager"]["role"] == "manager"
    finally:
        await engine.dispose()


@pytestmark_db
@pytest.mark.asyncio
async def test_a_rotated_link_stops_working():
    """The one thing to do when a link leaks."""
    from app.database import async_session, engine, run_migrations
    from app.exceptions import AppException
    from app.models.agency import Agency
    from app.routers.auth import auth_platform

    await run_migrations()
    try:
        async with async_session() as s:
            agency = Agency(name="Rotating Agency", base_city="Геленджик",
                            invite_token=secrets.token_hex(8))
            s.add(agency)
            await s.commit()
            old_token = agency.invite_token

        async with async_session() as s:
            agency = await s.get(Agency, agency.id)
            agency.invite_token = secrets.token_hex(8)
            await s.commit()

        init_data = build_tg_init_data(
            config.telegram_bot_token,
            {"id": 830000 + int(time.time()) % 100000, "first_name": "Опоздавший"})

        async with async_session() as s:
            with pytest.raises(AppException) as err:
                await auth_platform(
                    AuthRequest(platform="telegram", init_data=init_data,
                                invite=f"inv_{old_token}"), session=s)
        assert err.value.code == "INVITE_INVALID"
    finally:
        await engine.dispose()


@pytestmark_db
@pytest.mark.asyncio
async def test_only_the_owner_hands_out_invitations():
    from app.database import async_session, engine, run_migrations
    from app.dependencies import CurrentManager
    from app.exceptions import AppException
    from app.models.agency import Agency
    from app.models.manager import Manager
    from app.routers.auth import get_invite

    await run_migrations()
    try:
        async with async_session() as s:
            agency = Agency(name="Invite Agency", base_city="Геленджик",
                            invite_token=secrets.token_hex(8))
            s.add(agency)
            await s.flush()
            owner = Manager(agency_id=agency.id, name="Владелец", role="owner",
                            telegram_id=840000 + int(time.time()) % 10000, is_active=True)
            staff = Manager(agency_id=agency.id, name="Менеджер", role="manager",
                            telegram_id=850000 + int(time.time()) % 10000, is_active=True)
            s.add_all([owner, staff])
            await s.commit()
            agency_id = str(agency.id)
            owner_ctx = CurrentManager(manager_id=str(owner.id), agency_id=agency_id)
            staff_ctx = CurrentManager(manager_id=str(staff.id), agency_id=agency_id)

        async with async_session() as s:
            got = await get_invite(current=owner_ctx, session=s)
        assert got.link.startswith("https://t.me/")
        assert got.token in got.link

        async with async_session() as s:
            with pytest.raises(AppException) as err:
                await get_invite(current=staff_ctx, session=s)
        assert err.value.code == "OWNER_ONLY"
    finally:
        await engine.dispose()
