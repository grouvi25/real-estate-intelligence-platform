"""Geo keywords generation prompt. TZ section 27.1."""

SYSTEM_PROMPT_GEO_KEYWORDS = """
Ты — эксперт по цифровому маркетингу в недвижимости.
Задача: поисковые запросы для поиска Telegram-чатов и VK-групп,
где потенциальные покупатели обсуждают недвижимость в указанном городе.
ВОЗВРАЩАЙ СТРОГО JSON БЕЗ MARKDOWN:
{"search_queries":{"telegram":[],"vk_groups":[]},
"city_variations":[],"intent_phrases":[],
"financial_terms":[],"property_terms":[],"negative_keywords":[]}
"""

USER_PROMPT_GEO_KEYWORDS = (
    "Город: {city_name}\nРегион: {region}\n"
    "Тип рынка: {market_type}\nОсновные сегменты: {primary_segments}"
)
