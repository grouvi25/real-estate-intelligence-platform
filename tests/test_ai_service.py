"""Tests for AIService routing, budget guard, anonymization, and JSON parsing."""
import httpx
import pytest

from app.exceptions import AIBudgetExceededError
from app.services.ai_service import AIProvider, AIResponse, AIService, AIUsage, safe_ai_parse


class FakeTracker:
    def __init__(self, start: float = 0.0):
        self.total = start
        self.added: list[float] = []

    async def get_daily_cost(self, agency_id: str = "global") -> float:
        return self.total

    async def add_cost(self, cost: float, agency_id: str = "global") -> float:
        self.total += cost
        self.added.append(cost)
        return self.total

    async def reset_daily_cost(self, agency_id: str = "global") -> None:
        self.total = 0.0


def _yandex_response(text: str) -> dict:
    return {
        "result": {
            "alternatives": [{"message": {"role": "assistant", "text": text}}],
            "usage": {"inputTextTokens": "100", "completionTokens": "50", "totalTokens": "150"},
        }
    }


@pytest.mark.asyncio
async def test_complete_yandex_returns_text_and_tracks_cost():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "foundationModels" in str(request.url)
        return httpx.Response(200, json=_yandex_response('{"intent_score": 80}'))

    tracker = FakeTracker()
    ai = AIService(cost_tracker=tracker)
    ai.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    text = await ai.complete("system", "user text", "intent_scoring")
    await ai.close()

    assert '"intent_score"' in text
    # 150 tokens * 0.03 rub / 1000 = 0.0045
    assert tracker.added and round(tracker.added[0], 4) == 0.0045


@pytest.mark.asyncio
async def test_budget_exceeded_raises_before_call():
    ai = AIService(cost_tracker=FakeTracker(start=10_000))
    with pytest.raises(AIBudgetExceededError):
        await ai.complete("system", "user", "intent_scoring")
    await ai.close()


@pytest.mark.asyncio
async def test_foreign_provider_anonymizes_user_prompt():
    captured = {}

    async def fake_call_openai(system: str, user: str, model: str) -> AIResponse:
        captured["user"] = user
        return AIResponse(text="{}", model=model, provider=AIProvider.OPENAI, usage=AIUsage(1, 1, 2))

    ai = AIService(cost_tracker=FakeTracker())
    ai.provider = AIProvider.OPENAI
    ai._call_openai = fake_call_openai  # type: ignore[assignment]
    await ai.complete("system", "Иван Петров, тел +7 900 123-45-67", "intent_scoring")
    await ai.close()

    assert "[PHONE]" in captured["user"]
    assert "[NAME]" in captured["user"]
    assert "+7 900" not in captured["user"]


@pytest.mark.asyncio
async def test_provider_configured_false_without_keys():
    ai = AIService()
    assert ai.provider_configured is False  # test env has no provider credentials
    await ai.close()


def test_safe_ai_parse_plain():
    assert safe_ai_parse('{"a": 1}', {})["a"] == 1


def test_safe_ai_parse_markdown_fenced():
    raw = "```json\n{\"a\": 2, \"b\": \"x\"}\n```"
    parsed = safe_ai_parse(raw, {})
    assert parsed["a"] == 2 and parsed["b"] == "x"


def test_safe_ai_parse_garbage_returns_default():
    parsed = safe_ai_parse("totally not json", {"intent_score": 0})
    assert parsed["intent_score"] == 0
    assert parsed["parse_error"] is True
