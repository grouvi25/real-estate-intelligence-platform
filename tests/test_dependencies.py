"""Tests for the auth dependency get_current_manager."""
import pytest

from app.dependencies import get_current_manager
from app.exceptions import AppException
from app.security import create_access_token


@pytest.mark.asyncio
async def test_valid_bearer_token():
    token = create_access_token("mgr-1", agency_id="ag-1")
    cm = await get_current_manager(f"Bearer {token}")
    assert cm.manager_id == "mgr-1"
    assert cm.agency_id == "ag-1"


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
