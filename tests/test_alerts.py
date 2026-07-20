"""Tests for logging setup and critical alerts."""
import httpx
import pytest


def test_setup_logging_configures_structlog():
    import structlog

    from app.logging_config import setup_logging

    setup_logging()
    assert structlog.is_configured()
    structlog.get_logger().info("test event", key="value")  # must not raise


@pytest.mark.asyncio
async def test_alert_skipped_without_admin(monkeypatch):
    from app.config import config
    from app.services import alerts

    monkeypatch.setattr(config, "admin_telegram_id", None)
    assert await alerts.send_critical_alert("boom") is False


@pytest.mark.asyncio
async def test_alert_delivered(monkeypatch):
    import app.services.bot_abstraction as ba
    from app.config import config
    from app.services import alerts

    captured = {}

    async def fake_send(user_id, platform, message):
        captured["user_id"] = user_id
        captured["text"] = message.text
        return True

    monkeypatch.setattr(config, "admin_telegram_id", 555)
    monkeypatch.setattr(ba.bot_layer, "send_message", fake_send)

    assert await alerts.send_critical_alert("disk full") is True
    assert captured["user_id"] == 555
    assert "CRITICAL ALERT" in captured["text"]
    assert "disk full" in captured["text"]


@pytest.mark.asyncio
async def test_ai_budget_alert_fires_over_90_percent(monkeypatch):
    import app.services.alerts as alerts_mod
    from app.services.ai_service import AIService

    fired = []

    async def fake_alert(msg):
        fired.append(msg)
        return True

    monkeypatch.setattr(alerts_mod, "send_critical_alert", fake_alert)

    class Tracker:
        def __init__(self):
            self.total = 0.0

        async def get_daily_cost(self, agency_id="global"):
            return self.total

        async def add_cost(self, cost, agency_id="global"):
            self.total += cost
            return self.total

    def handler(request):
        return httpx.Response(
            200,
            json={
                "result": {
                    "alternatives": [{"message": {"text": "{}"}}],
                    "usage": {"inputTextTokens": "100", "completionTokens": "50", "totalTokens": "150"},
                }
            },
        )

    ai = AIService(cost_tracker=Tracker())
    ai.daily_budget = 0.004  # 150 tokens * 0.03/1000 = 0.0045 > 90% of 0.004
    ai.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await ai.complete("system", "user", "intent_scoring")
    await ai.close()

    assert fired, "budget alert should fire above 90%"
