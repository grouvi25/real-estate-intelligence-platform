"""Tests for JWT security helpers."""
from datetime import timedelta

import pytest

from app.security import TokenError, create_access_token, decode_access_token


def test_create_and_decode_roundtrip():
    token = create_access_token(subject="manager-123", agency_id="agency-1")
    payload = decode_access_token(token)
    assert payload["sub"] == "manager-123"
    assert payload["agency_id"] == "agency-1"
    assert "exp" in payload
    assert "iat" in payload


def test_extra_claims():
    token = create_access_token(subject="m1", extra_claims={"role": "admin"})
    payload = decode_access_token(token)
    assert payload["role"] == "admin"


def test_expired_token_raises():
    token = create_access_token(subject="m1", expires_delta=timedelta(seconds=-1))
    with pytest.raises(TokenError, match="expired"):
        decode_access_token(token)


def test_tampered_token_raises():
    token = create_access_token(subject="m1")
    tampered = token[:-3] + ("abc" if not token.endswith("abc") else "xyz")
    with pytest.raises(TokenError):
        decode_access_token(tampered)


def test_garbage_token_raises():
    with pytest.raises(TokenError, match="Invalid"):
        decode_access_token("not-a-jwt")
