"""Regression coverage for the deep three-specification corrective audit."""
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_owner_guard_rejects_manager_and_accepts_owner():
    from app.dependencies import CurrentManager, require_owner
    from app.exceptions import AppException

    current = CurrentManager(manager_id="00000000-0000-0000-0000-000000000001",
                             agency_id="00000000-0000-0000-0000-000000000002")

    class Session:
        role = "manager"
        async def get(self, _model, _id):
            return SimpleNamespace(agency_id=current.agency_id, role=self.role)

    session = Session()
    with pytest.raises(AppException) as exc:
        await require_owner(session, current)
    assert exc.value.status_code == 403
    session.role = "owner"
    await require_owner(session, current)


@pytest.mark.asyncio
async def test_invalid_knowledge_response_is_not_saved_as_learned(monkeypatch):
    import app.services.ai_service as ai_module
    from worker.tasks.knowledge_tasks import _recompute_ai_weights

    class AI:
        async def complete(self, *_args): return "not-json"
        async def close(self): pass

    monkeypatch.setattr(ai_module, "AIService", AI)
    agency = SimpleNamespace(settings={})

    class Session:
        async def get(self, _model, _id): return agency

    result = await _recompute_ai_weights(Session(), [SimpleNamespace(agency_id="a")])
    assert result == {}
    assert "knowledge_moat_weights" not in agency.settings


def test_signal_bus_migration_enforces_approved_contract():
    from pathlib import Path
    sql = Path("migrations/055_corrective_conformance.sql").read_text(encoding="utf-8")
    assert "origin_system SET DEFAULT 'reip_scouting'" in sql
    assert "origin_system SET NOT NULL" in sql
    assert "reply_status IN ('pending','replied','escalated','dismissed')" in sql
    assert "connector_type" in sql
    assert "topic_tag" in sql and "content_title" in sql


def test_canonical_channel_aliases_are_registered():
    from app.services.channels import get_channel_adapter
    assert get_channel_adapter("tg_bot").channel == "telegram"
    assert get_channel_adapter("max_bot").channel == "max"
    assert get_channel_adapter("vk_api").channel == "vk"
    assert get_channel_adapter("avito_api").channel == "avito"
    assert get_channel_adapter("cian_api").channel == "cian"


@pytest.mark.asyncio
async def test_classified_adapter_uses_configured_official_api(monkeypatch):
    import httpx
    from app.config import config
    from app.services.channels import get_channel_adapter

    monkeypatch.setattr(config, "avito_api_base_url", "https://avito.test")
    monkeypatch.setattr(config, "avito_api_token", "token")
    seen = {}

    async def fake_post(self, url, **kwargs):
        seen["url"] = url
        seen["auth"] = kwargs["headers"]["Authorization"]
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    adapter = get_channel_adapter("avito_api")
    assert adapter.reply_supported() is True
    result = await adapter.send_reply("dialog-7", "hello")
    assert result["sent"] is True
    assert seen == {"url": "https://avito.test/messages/dialog-7", "auth": "Bearer token"}


@pytest.mark.asyncio
async def test_telethon_auth_pause_sets_six_hour_ttl_and_alerts(monkeypatch):
    import redis.asyncio as redis
    import app.services.alerts as alerts
    from telethon.errors import SessionRevokedError
    from worker.tasks.collector_tasks import _pause_telethon

    calls = {}
    class Redis:
        async def setex(self, key, ttl, value): calls["redis"] = (key, ttl, value)
        async def aclose(self): pass
    async def alert(message):
        calls["alert"] = message
        return True

    monkeypatch.setattr(redis, "from_url", lambda *_a, **_k: Redis())
    monkeypatch.setattr(alerts, "send_critical_alert", alert)
    await _pause_telethon(SessionRevokedError(None))
    assert calls["redis"] == ("telethon:paused_until", 6 * 3600, "1")
    assert "telethon_login.py" in calls["alert"]


def test_admin_landing_matches_tz_route():
    from pathlib import Path
    app = Path("mini_app/js/app.js").read_text(encoding="utf-8")
    admin = Path("mini_app/js/screens/admin.js").read_text(encoding="utf-8")
    assert "['admin', () => Screens.admin()]" in app
    assert "Screens.admin = async function" in admin
    assert 'data-go="admin/geo"' in admin
    assert 'data-go="admin/sources"' in admin
    assert "role === 'owner'" in admin
