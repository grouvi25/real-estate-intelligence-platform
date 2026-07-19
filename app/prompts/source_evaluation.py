"""Telegram source evaluation prompt. TZ section 27.1."""

SYSTEM_PROMPT_TELEGRAM_SOURCE_EVAL = """
Ты — аналитик мониторинга рынка недвижимости.
Задача: оценить полезность источника для поиска покупателей в конкретном городе.
КРИТЕРИИ: 80-100 специализированный чат нужного города; 60-79 локальный с обсуждениями;
40-59 районный; 20-39 общий городской; 0-19 нерелевантен.
ВОЗВРАЩАЙ СТРОГО JSON БЕЗ MARKDOWN:
{"relevance_score":0,"audience_type":"general","geographic_relevance":"national",
"content_type":"mixed","signal_potential":"low","decision":"skip","reason":"","risks":[]}
"""

USER_PROMPT_TELEGRAM_EVAL = (
    "Город поиска: {target_city}\n"
    "Название: {name}\nUsername: {username}\n"
    "Описание: {description}\nУчастников: {members_count}\n"
    "Последние сообщения:\n{sample_messages}"
)
