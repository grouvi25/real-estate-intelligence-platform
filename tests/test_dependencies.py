"""Tests for the auth dependency get_current_manager."""
import pytest

from app.dependencies import get_current_manager
from app.exceptions import AppException
from app.security import create_access_token


@pytest.mark.asyncio
async def test_valid_bearer_token(monkeypatch):
    import app.database as db
    from types import SimpleNamespace
    class Session:
        async def get(self, _model, _id): return SimpleNamespace(is_active=True, agency_id="00000000-0000-0000-0000-000000000002")
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): pass
    monkeypatch.setattr(db, "async_session", lambda: Session())
    token = create_access_token("00000000-0000-0000-0000-000000000001", agency_id="00000000-0000-0000-0000-000000000002")
    cm = await get_current_manager(f"Bearer {token}")
    assert cm.manager_id == "00000000-0000-0000-0000-000000000001"
    assert cm.agency_id == "00000000-0000-0000-0000-000000000002"


@pytest.mark.asyncio
async def test_missing_header_401():
    with pytest.raises(AppException) as exc:
        await get_current_manager(None)
    assert exc.value.status_code == 401
    assert exc.value.code == "UNAUTHORIZED"


@pytest.mark.asyncio
async def test_wrong_scheme_401():
    with pytest.raises(AppException):
        await get_current_manager("Token abc")


@pytest.mark.asyncio
async def test_invalid_token_401():
    with pytest.raises(AppException) as exc:
        await get_current_manager("Bearer not.a.valid.jwt")
    assert exc.value.code == "INVALID_TOKEN"


@pytest.mark.asyncio
async def test_missing_agency_claim_401():
    token = create_access_token("mgr-1")  # no agency_id claim
    with pytest.raises(AppException):
        await get_current_manager(f"Bearer {token}")
