"""Non-DB tests for AI-backed endpoints (market-event, listing).

AIService is monkeypatched so no network/provider is required. The market-event
endpoint doesn't touch the DB, so it runs everywhere; the listing endpoint's
DB path is covered by the DB-gated product-extension suite.
"""
import pytest

from app.dependencies import CurrentManager


class _FakeAI:
    """Stand-in for AIService that records the prompt and returns fixed JSON."""

    last_user = None

    def __init__(self, *args, **kwargs):
        pass

    async def complete(self, system, user, module, agency_id="global"):
        _FakeAI.last_user = user
        assert module == "market_analysis"
        return (
            '{"event_type":"mortgage_rate","significance":"high",'
            '"impact_on_agency":"рост спроса","affected_segments":["family"],'
            '"recommended_action":"усилить рекламу","urgency":"act_now",'
            '"summary":"ставка снижена"}'
        )

    async def close(self):
        pass


@pytest.mark.asyncio
async def test_market_event_endpoint_parses_analysis(monkeypatch):
    import app.services.ai_service as ai_module
    from app.routers.analytics import MarketEventRequest, analyze_market_event

    monkeypatch.setattr(ai_module, "AIService", _FakeAI)

    req = MarketEventRequest(
        city="Геленджик", event_type="mortgage_rate",
        event_data="Ставка ЦБ снижена до 12%",
    )
    current = CurrentManager(manager_id="m1", agency_id="a1")
    result = await analyze_market_event(req=req, current=current, session=None)

    analysis = result["analysis"]
    assert analysis["significance"] == "high"
    assert analysis["affected_segments"] == ["family"]
    assert "act_now" in analysis["urgency"]
    # The prompt carries the city + event data through to the model.
    assert "Геленджик" in _FakeAI.last_user
    assert "12%" in _FakeAI.last_user
