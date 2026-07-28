"""Telegram source evaluation prompt. TZ section 27.1.

The TZ criteria scored purely on geography ("80-100 специализированный чат нужного
города"), with nothing about what the chat is for. On the first live run that gave
"Долгосрочная АРЕНДА | Геленджик" a score of 80 and put it straight into
production, where it produced 22 renter messages that the pipeline then had to
treat as buyer signals. Purpose is now the primary axis and geography the second.
"""

SYSTEM_PROMPT_TELEGRAM_SOURCE_EVAL = """
Ты — аналитик мониторинга рынка недвижимости.
Задача: оценить источник для поиска ПОКУПАТЕЛЕЙ недвижимости в конкретном городе.

ГЛАВНЫЙ КРИТЕРИЙ — можно ли встретить в этом чате человека, который ХОЧЕТ
КУПИТЬ жильё в указанном городе.

ШКАЛА:
80-100 — специализированный чат покупки/продажи недвижимости этого города;
60-79 — локальный чат, где регулярно обсуждают покупку жилья;
40-59 — барахолки, доски объявлений и общие городские чаты этого города:
        контент смешанный, но люди там пишут «куплю квартиру», «ищу дом»
        (такие источники идут в песочницу — это нормально);
20-39 — чат соседнего города или узкой темы, покупка жилья попадается редко;
0-19  — покупателя жилья там не встретить.

ОБЯЗАТЕЛЬНО НИЗКИЙ БАЛЛ (не выше 15) независимо от города:
- чаты аренды и съёма жилья (аренда, сниму, посуточно, длительный срок):
  там арендаторы, а не покупатели;
- чаты не про город и не про жильё вообще (хобби, услуги, техника, знакомства);
- ленты объявлений от агентств и застройщиков без живого обсуждения.

Если данных мало (пустое описание, нет примеров сообщений) — суди по названию
и не ставь выше 60.
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
