"""LM-4: district map by life scenario. TZ section 29.3 (exact spec).

The TZ uses an AI prompt (SYSTEM_PROMPT_DISTRICTS) to return top-3 districts for
a life scenario. We keep the prompt + scenarios here; the router calls the AI and
falls back to a lightweight data-driven recommender if AI is unavailable, so the
endpoint never hard-fails.
"""
from __future__ import annotations

SYSTEM_PROMPT_DISTRICTS = """
Ты — эксперт по недвижимости черноморского побережья.
Задача: топ-3 района по сценарию жизни покупателя (только реальные факты).
ВОЗВРАЩАЙ СТРОГО JSON БЕЗ MARKDOWN:
{"districts":[{"name":"","description":"","why_fits":"","pros":[],"cons":[],
"price_range":"","score":0}],"city_overview":"","recommendation":""}
"""

LIFE_SCENARIOS = {
    "family": "Семья с детьми: школа рядом, детская площадка, безопасный двор",
    "investor": "Инвестор: ликвидность, туристический поток, аренда",
    "relocant": "Переезд на ПМЖ: инфраструктура, работа, комьюнити",
    "remote": "Удалённая работа: тишина, быстрый интернет, кофейни",
    "senior": "Пенсионеры: тишина, поликлиника рядом, зелёные зоны",
    "vacationer": "Отдых: близость к морю, развлечения, парковка",
}

# Lightweight fallback data used only when the AI provider is not configured.
_FALLBACK_DISTRICTS = {
    "Геленджик": [
        {"name": "Центр", "why_fits": "Вся инфраструктура в шаговой доступности",
         "pros": ["набережная", "магазины", "рестораны"], "cons": ["летом шумно"],
         "price_range": "180 000–260 000 ₽/м²", "score": 80},
        {"name": "Тонкий мыс", "why_fits": "Тихий район у моря",
         "pros": ["море рядом", "спокойно"], "cons": ["дальше от центра"],
         "price_range": "160 000–230 000 ₽/м²", "score": 75},
        {"name": "Толстый мыс", "why_fits": "Видовые квартиры, престиж",
         "pros": ["виды", "новостройки"], "cons": ["выше цена"],
         "price_range": "200 000–300 000 ₽/м²", "score": 72},
    ],
}


def fallback_districts(city: str, scenario: str) -> dict:
    districts = _FALLBACK_DISTRICTS.get(city, [])
    return {
        "districts": districts,
        "city_overview": f"{city}: подборка районов под сценарий «{scenario}».",
        "recommendation": "Уточните бюджет — менеджер подберёт объекты в выбранном районе.",
        "ai_used": False,
    }
