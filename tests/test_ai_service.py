"""Tests for AIService routing, budget guard, anonymization, and JSON parsing."""
import httpx
import pytest

from app.config import config
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
    # 150 токенов * 0.20 ₽ / 1000 = 0.03
    assert tracker.added and round(tracker.added[0], 4) == 0.03


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


@pytest.mark.asyncio
async def test_complete_gigachat_oauth_then_chat(monkeypatch):
    from app.config import config

    monkeypatch.setattr(config, "gigachat_verify_ssl", True)  # use mocked self.http
    monkeypatch.setattr(config, "gigachat_client_id", "cid")
    monkeypatch.setattr(config, "gigachat_client_secret", "csecret")

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "oauth" in url:
            assert request.headers.get("RqUID")
            assert request.headers["Authorization"].startswith("Basic ")
            return httpx.Response(200, json={"access_token": "tok-123", "expires_at": 0})
        assert "chat/completions" in url
        assert request.headers["Authorization"] == "Bearer tok-123"
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": '{"ok": true}'}}],
            "usage": {"prompt_tokens": 40, "completion_tokens": 60, "total_tokens": 100},
        })

    tracker = FakeTracker()
    ai = AIService(cost_tracker=tracker)
    ai.provider = AIProvider.GIGACHAT
    ai.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    text = await ai.complete("system", "user", "intent_scoring")
    await ai.close()

    assert '"ok"' in text
    # 100 tokens * 0.20 rub / 1000 = 0.02
    assert tracker.added and round(tracker.added[0], 4) == 0.02


@pytest.mark.asyncio
async def test_complete_anthropic_via_proxy_anonymizes(monkeypatch):
    from app.config import config

    monkeypatch.setattr(config, "railway_proxy_url", "https://proxy.test")
    monkeypatch.setattr(config, "railway_proxy_secret", "psecret")
    monkeypatch.setattr(config, "anthropic_api_key", "sk-ant-xxx")

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://proxy.test/anthropic/v1/messages"
        assert request.headers["x-api-key"] == "sk-ant-xxx"
        assert request.headers["X-Proxy-Secret"] == "psecret"
        assert request.headers["anthropic-version"] == "2023-06-01"
        import json as _json

        captured["user"] = _json.loads(request.content)["messages"][0]["content"]
        return httpx.Response(200, json={
            "content": [{"type": "text", "text": '{"score": 5}'}],
            "usage": {"input_tokens": 12, "output_tokens": 8},
        })

    tracker = FakeTracker()
    ai = AIService(cost_tracker=tracker)
    ai.provider = AIProvider.ANTHROPIC
    ai.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    text = await ai.complete("system", "Иван Петров, тел +7 900 123-45-67", "intent_scoring")
    await ai.close()

    assert '"score"' in text
    # 152-FZ: PII is stripped before the foreign provider.
    assert "[PHONE]" in captured["user"] and "[NAME]" in captured["user"]
    assert "+7 900" not in captured["user"]


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


# --- the provider is an operator's choice, not a deploy ----------------------

@pytest.mark.asyncio
async def test_the_stored_provider_wins_over_the_env(monkeypatch):
    """TZ 2.2 calls the providers switchable from the admin area, and 35.4 asks
    for it without a restart. It was AI_DEFAULT_PROVIDER in .env -- so moving off
    a foreign provider, a 152-ФЗ decision, meant editing a file on the server."""
    from app.services import platform_settings
    from app.services.ai_service import AIProvider, AIService

    monkeypatch.setattr(config, "ai_default_provider", AIProvider.OPENAI)

    async def stored(key):
        return "yandexgpt"

    monkeypatch.setattr(platform_settings, "get_setting", stored)

    service = AIService()
    try:
        assert service.provider == AIProvider.OPENAI
        assert await service.resolve_provider() == AIProvider.YANDEX_GPT
    finally:
        await service.http.aclose()


@pytest.mark.asyncio
async def test_nothing_stored_leaves_the_configured_provider(monkeypatch):
    from app.services import platform_settings
    from app.services.ai_service import AIProvider, AIService

    monkeypatch.setattr(config, "ai_default_provider", AIProvider.GIGACHAT)

    async def stored(key):
        return None

    monkeypatch.setattr(platform_settings, "get_setting", stored)

    service = AIService()
    try:
        assert await service.resolve_provider() == AIProvider.GIGACHAT
    finally:
        await service.http.aclose()


@pytest.mark.asyncio
async def test_an_unknown_stored_provider_is_ignored(monkeypatch):
    """A bad row must not take AI down; the configured provider carries on."""
    from app.services import platform_settings
    from app.services.ai_service import AIProvider, AIService

    monkeypatch.setattr(config, "ai_default_provider", AIProvider.YANDEX_GPT)

    async def stored(key):
        return "deepseek"

    monkeypatch.setattr(platform_settings, "get_setting", stored)

    service = AIService()
    try:
        assert await service.resolve_provider() == AIProvider.YANDEX_GPT
    finally:
        await service.http.aclose()
