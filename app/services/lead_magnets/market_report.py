"""LM-5: personalized market report. TZ section 29 (LM-5)."""
from __future__ import annotations

from typing import Optional

from app.services.ai_service import AIService, safe_ai_parse

SYSTEM_PROMPT_MARKET_REPORT = """
Ты — аналитик рынка недвижимости черноморского побережья.
Сформируй персональный рыночный отчёт для потенциального покупателя.
Не выдумывай точные факты, которых нет во входных данных: обозначай оценки.
Верни строго JSON без markdown:
{"city":"","segment":"","price_range_min":0,"price_range_max":0,
"market_trend":"stable","demand_level":"medium","typical_objects":[],
"risks":[],"opportunities":[],"recommended_action":"","summary":""}
"""

USER_PROMPT_MARKET_REPORT = (
    "Город: {city}\nСегмент покупателя: {segment}\n"
    "Бюджет: {budget_min}-{budget_max} ₽\nЦель покупки: {goal}"
)


def _fallback(city: str, segment: str, budget_min: Optional[int], budget_max: Optional[int]) -> dict:
    return {
        "city": city,
        "segment": segment,
        "price_range_min": budget_min or 0,
        "price_range_max": budget_max or 0,
        "market_trend": "unknown",
        "demand_level": "medium",
        "typical_objects": [],
        "risks": [],
        "opportunities": [],
        "recommended_action": "Уточнить актуальные предложения у менеджера",
        "summary": "Для точного отчёта нужны актуальные рыночные данные.",
    }


async def generate_market_report(
    city: str,
    segment: str,
    budget_min: Optional[int] = None,
    budget_max: Optional[int] = None,
    goal: str = "own",
) -> dict:
    fallback = _fallback(city, segment, budget_min, budget_max)
    ai = AIService()
    try:
        user_prompt = USER_PROMPT_MARKET_REPORT.format(
            city=city,
            segment=segment,
            budget_min=budget_min or 0,
            budget_max=budget_max or 0,
            goal=goal,
        )
        response = await ai.complete(
            SYSTEM_PROMPT_MARKET_REPORT, user_prompt, "market_analysis")
        return safe_ai_parse(response, fallback)
    except Exception:
        # A public lead magnet must still return a useful, typed response while
        # the selected AI provider is unavailable or its daily budget is closed.
        return fallback
    finally:
        await ai.close()
