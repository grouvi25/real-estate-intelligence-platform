"""Acceptance coverage for the August 2026 fixes."""
from types import SimpleNamespace

import pytest


def test_qualification_exists_for_every_provider():
    from app.config import config

    assert config.ai_models["qualification"] == "yandexgpt-lite"
    expected = set(config.ai_models)
    assert set(config.openai_models) == expected
    assert set(config.gigachat_models) == expected
    assert set(config.anthropic_models) == expected


def test_documents_alias_exports_render_pdf():
    from app.services.documents import render_pdf

    assert callable(render_pdf)


@pytest.mark.asyncio
async def test_lm5_report_uses_market_analysis(monkeypatch):
    import app.services.lead_magnets.market_report as module

    seen = {}

    class FakeAI:
        async def complete(self, system, user, task):
            seen["task"] = task
            return '{"city":"Геленджик","segment":"investor","price_range_min":5000000,"price_range_max":9000000,"market_trend":"up","demand_level":"high","typical_objects":[],"risks":[],"opportunities":[],"recommended_action":"смотреть","summary":"рынок растёт"}'

        async def close(self):
            pass

    monkeypatch.setattr(module, "AIService", FakeAI)
    result = await module.generate_market_report(
        "Геленджик", "investor", 5_000_000, 9_000_000, "invest")
    assert seen["task"] == "market_analysis"
    assert result["price_range_min"] == 5_000_000
    assert result["recommended_action"]


@pytest.mark.asyncio
async def test_lm5_subscribe_requires_consent():
    from app.exceptions import ConsentRequiredError
    from app.routers.lead_magnets import LM5SubscribeRequest, lm5_subscribe

    request = LM5SubscribeRequest(
        agency_id="00000000-0000-0000-0000-000000000001",
        city="Геленджик",
        segment="investor",
        contact_name="Иван",
        contact_phone="+79000000000",
        consent_given=False,
    )
    with pytest.raises(ConsentRequiredError):
        await lm5_subscribe(request, session=None)


@pytest.mark.asyncio
async def test_matching_weights_endpoint_reports_source():
    from app.routers.analytics import get_matching_weights

    agency = SimpleNamespace(settings={
        "knowledge_moat_weights": {"budget_weight": 31},
        "knowledge_moat_updated_at": "2026-08-12T00:00:00+00:00",
    })

    class Session:
        async def get(self, _model, _id):
            return agency

    current = SimpleNamespace(agency_id="00000000-0000-0000-0000-000000000001")
    result = await get_matching_weights(current=current, session=Session())
    assert result["source"] == "learned"
    assert result["updated_at"]


@pytest.mark.asyncio
async def test_knowledge_weights_are_validated_and_timestamped(monkeypatch):
    import app.services.ai_service as ai_module
    from worker.tasks.knowledge_tasks import _recompute_ai_weights

    class FakeAI:
        async def complete(self, *_args):
            return '{"budget":99,"segment_weight":25,"location_weight":20,"priorities_weight":15,"urgency_weight":10}'

        async def close(self):
            pass

    monkeypatch.setattr(ai_module, "AIService", FakeAI)
    agency = SimpleNamespace(settings={})

    class Session:
        async def get(self, _model, _id):
            return agency

    weights = await _recompute_ai_weights(
        Session(), [SimpleNamespace(agency_id="agency-1")])
    assert weights == {
        "segment_weight": 25,
        "location_weight": 20,
        "priorities_weight": 15,
        "urgency_weight": 10,
    }
    assert "budget_weight" not in weights
    assert agency.settings["knowledge_moat_updated_at"]


def test_source_dto_exposes_last_signal_at():
    from datetime import datetime, timezone

    from app.routers.sources import _source_dto

    source = SimpleNamespace(
        id="s", source_name="x", source_url="https://example.test",
        source_type="rss", external_id=None, status="active", score=1,
        signals_per_day=0, auto_found=False, geo_location_id=None,
        last_checked_at=None, created_at=None,
    )
    now = datetime.now(timezone.utc)
    result = _source_dto(source, 3, "Сочи", now)
    assert result["signal_count"] == 3
    assert result["last_signal_at"] == now.isoformat()


def test_admin_bundle_and_deploy_assets_exist():
    from pathlib import Path

    root = Path(__file__).parents[1]
    index = (root / "mini_app/index.html").read_text(encoding="utf-8")
    assert "screens/admin.js" in index
    assert "admin/geo" in (root / "mini_app/js/app.js").read_text(encoding="utf-8")
    assert (root / "railway_proxy/server.js").is_file()
    assert (root / "nginx/nginx.conf").is_file()
    assert (root / "migrations/README.md").is_file()
