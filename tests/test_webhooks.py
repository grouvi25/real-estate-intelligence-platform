"""Tests for platform webhooks (Telegram secret-token verification)."""
from fastapi.testclient import TestClient

from app.main import app


def test_telegram_webhook_rejects_bad_secret(monkeypatch):
    from app.config import config

    monkeypatch.setattr(config, "telegram_webhook_secret", "s3cr3t")
    client = TestClient(app)
    r = client.post(
        "/api/webhooks/telegram",
        json={"update_id": 1},
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
    )
    assert r.status_code == 403
    assert r.json()["code"] == "FORBIDDEN"


def test_telegram_webhook_accepts_good_secret(monkeypatch):
    from app.config import config

    monkeypatch.setattr(config, "telegram_webhook_secret", "s3cr3t")
    client = TestClient(app)
    r = client.post(
        "/api/webhooks/telegram",
        json={"update_id": 1},
        headers={"X-Telegram-Bot-Api-Secret-Token": "s3cr3t"},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_telegram_webhook_accepts_when_no_secret_configured(monkeypatch):
    from app.config import config

    monkeypatch.setattr(config, "telegram_webhook_secret", None)
    client = TestClient(app)
    r = client.post("/api/webhooks/telegram", json={"update_id": 2})
    assert r.status_code == 200
