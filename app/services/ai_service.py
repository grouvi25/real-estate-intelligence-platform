"""AI service: provider routing, PII anonymization, budget guard, cost logging.

TZ sections 10.2 + 27.0/27.1 (fixed):
- AIUsage / AIResponse are dataclasses (the illustrative TZ used bare classes
  with keyword construction, which would fail).
- Budget is enforced via the shared RedisCostTracker instead of a per-process
  ``self.daily_cost_rub`` counter.
- Budget overflow raises AIBudgetExceededError (handled in app/main.py).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum

import httpx
import structlog

from app.config import config
from app.exceptions import AIBudgetExceededError
from app.services.pii_anonymizer import anonymize

logger = structlog.get_logger()


class AIProvider(str, Enum):
    YANDEX_GPT = "yandexgpt"
    GIGACHAT = "gigachat"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


@dataclass
class AIUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class AIResponse:
    text: str
    model: str
    provider: AIProvider
    usage: AIUsage = field(default_factory=AIUsage)


# Rates in RUB per 1000 tokens (May 2026 estimates), TZ 10.2.
_RATES_PER_1K = {
    "yandexgpt-lite": 0.03,
    "yandexgpt-pro": 0.06,
    "gpt-4o-mini": 5.0,
    "gpt-4o": 45.0,
}


class AIService:
    def __init__(self, cost_tracker=None):
        self.http = httpx.AsyncClient(timeout=60.0)
        self.provider: AIProvider = AIProvider(config.ai_default_provider)
        self.daily_budget: float = config.ai_daily_budget_rub
        self._cost_tracker_override = cost_tracker

    # --- cost tracker resolution ---
    def _tracker(self):
        from app.services import ai_cost_tracker

        tracker = self._cost_tracker_override or ai_cost_tracker.cost_tracker
        if tracker is None:
            raise RuntimeError("AI cost tracker is not initialized (call init_cost_tracker)")
        return tracker

    @property
    def provider_configured(self) -> bool:
        """Whether the selected provider has the credentials it needs."""
        if self.provider == AIProvider.YANDEX_GPT:
            return bool(config.yandex_gpt_api_key and config.yandex_gpt_folder_id)
        if self.provider == AIProvider.GIGACHAT:
            return bool(config.gigachat_client_id and config.gigachat_client_secret)
        if self.provider in (AIProvider.OPENAI, AIProvider.ANTHROPIC):
            return bool(config.railway_proxy_url and config.railway_proxy_secret)
        return False

    async def complete(self, system: str, user: str, module: str, agency_id: str = "global") -> str:
        """Main entrypoint: routing, budget guard, anonymization, cost logging."""
        tracker = self._tracker()
        current_cost = await tracker.get_daily_cost(agency_id)
        if current_cost >= self.daily_budget:
            logger.error("AI budget exceeded", cost=current_cost, budget=self.daily_budget)
            raise AIBudgetExceededError()

        # 1. Anonymize before foreign providers (152-FZ).
        if self.provider in (AIProvider.OPENAI, AIProvider.ANTHROPIC):
            user = anonymize(user)

        # 2. Model selection by task.
        model = config.ai_models.get(module, "yandexgpt-lite")

        # 3. Dispatch.
        if self.provider == AIProvider.YANDEX_GPT:
            response = await self._call_yandex(system, user, model)
        elif self.provider == AIProvider.OPENAI:
            response = await self._call_openai(system, user, model)
        else:
            raise NotImplementedError(f"Provider {self.provider} not implemented")

        # 4. Cost accounting.
        cost = response.usage.total_tokens * self._get_rate_per_token(model) / 1000
        total = await tracker.add_cost(cost, agency_id)
        logger.info(
            "AI call completed",
            module=module,
            provider=self.provider.value,
            model=model,
            tokens=response.usage.total_tokens,
            cost_rub=round(cost, 3),
        )
        # 5. Soft budget alert at 90% (best-effort, never blocks the call).
        if self.daily_budget and total >= 0.9 * self.daily_budget:
            try:
                from app.services.alerts import send_critical_alert

                await send_critical_alert(
                    f"AI-бюджет: {round(total, 2)}/{self.daily_budget} ₽ (>90%), agency={agency_id}"
                )
            except Exception:  # noqa: BLE001
                pass
        return response.text

    async def _call_yandex(self, system: str, user: str, model: str) -> AIResponse:
        url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
        headers = {
            "Authorization": f"Api-Key {config.yandex_gpt_api_key}",
            "x-folder-id": config.yandex_gpt_folder_id or "",
            "Content-Type": "application/json",
        }
        payload = {
            "modelUri": f"gpt://{config.yandex_gpt_folder_id}/{model}/latest",
            "completionOptions": {"stream": False, "temperature": 0.2, "maxTokens": 2000},
            "messages": [
                {"role": "system", "text": system},
                {"role": "user", "text": user},
            ],
        }
        resp = await self.http.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        result = data["result"]
        # YandexGPT returns token usage under result.usage (inputTextTokens/
        # completionTokens/totalTokens, as strings). Fall back gracefully.
        usage_src = result.get("usage") or result.get("numTokens") or {}
        prompt_tokens = int(usage_src.get("inputTextTokens") or usage_src.get("promptTokens") or 0)
        completion_tokens = int(usage_src.get("completionTokens") or 0)
        total_tokens = int(usage_src.get("totalTokens") or (prompt_tokens + completion_tokens))
        usage = AIUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
        text = result["alternatives"][0]["message"]["text"]
        return AIResponse(text=text, model=model, provider=AIProvider.YANDEX_GPT, usage=usage)

    async def _call_openai(self, system: str, user: str, model: str) -> AIResponse:
        # Foreign provider is called via the Railway proxy (152-FZ compliance).
        url = f"{config.railway_proxy_url}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {config.railway_proxy_secret}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "max_tokens": 2000,
            "response_format": {"type": "json_object"},
        }
        resp = await self.http.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        u = data.get("usage", {})
        usage = AIUsage(
            prompt_tokens=int(u.get("prompt_tokens", 0)),
            completion_tokens=int(u.get("completion_tokens", 0)),
            total_tokens=int(u.get("total_tokens", 0)),
        )
        text = data["choices"][0]["message"]["content"]
        return AIResponse(text=text, model=model, provider=AIProvider.OPENAI, usage=usage)

    def _get_rate_per_token(self, model: str) -> float:
        return _RATES_PER_1K.get(model, 0.1)

    async def close(self) -> None:
        await self.http.aclose()


def safe_ai_parse(response_text: str, default: dict) -> dict:
    """Parse JSON returned by an LLM, tolerating markdown fences and prose."""
    try:
        return json.loads(response_text)
    except (json.JSONDecodeError, TypeError):
        match = re.search(r"\{.*\}", response_text or "", re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    logger.warning("AI response parse failed", raw=(response_text or "")[:200])
    return {**default, "parse_error": True, "raw_response": (response_text or "")[:200]}
