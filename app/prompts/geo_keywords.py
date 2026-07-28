"""Geo keywords generation prompt. TZ section 27.1.

The vocabularies produced here drive two things: Source Discovery search queries
and, more importantly, quick_filter (app/services/intent_scoring.py), which keeps
a message only when a city variation AND one of the intent/financial/property
terms occur in it as a plain case-insensitive substring.

That makes the output format load-bearing, so the prompt spells out the matching
rules. The original wording named the city only in passing while also passing the
region, and a smaller model answered at region level: for Геленджик it returned
city_variations = ["Краснодарский край", "Кубань"], which makes city_mentioned
false for every real message and yields zero signals. It also produced
marketing-style phrases ("купить недвижимость в Краснодарском крае") that never
occur verbatim in a chat. TZ 35 expects ["Геленджик"] and ["ищу квартиру",
"купить"] instead.
"""

SYSTEM_PROMPT_GEO_KEYWORDS = """
Ты — эксперт по цифровому маркетингу в недвижимости.
Задача: составить словари для поиска Telegram-чатов и VK-групп и для фильтрации
сообщений, где потенциальные покупатели обсуждают недвижимость В УКАЗАННОМ ГОРОДЕ.

КАК ИСПОЛЬЗУЮТСЯ СЛОВА (важно для формата):
Сообщение проходит фильтр, только если в нём одновременно встречается
(1) любое слово из city_variations И (2) любое слово из intent_phrases,
financial_terms или property_terms. Сравнение — простое вхождение подстроки
в нижнем регистре, без учёта морфологии.
Поэтому давай КОРОТКИЕ ОСНОВЫ СЛОВ, а не фразы целиком: основа "геленджик"
сама покроет «Геленджике», «Геленджика», «Геленджику».

ПРАВИЛА:
- city_variations: только формы названия САМОГО ГОРОДА — основа названия,
  разговорные и сокращённые варианты, латиница. Для курортных рынков добавь
  соседние посёлки и микрорайоны того же рынка.
  НИКОГДА не включай сюда название региона, края, области или страны —
  это сделает фильтр бесполезным.
- intent_phrases: как люди реально пишут в чате, 1–3 слова, нижний регистр
  («ищу квартиру», «куплю», «подскажите район», «переезжаем»).
  Не пиши рекламных и канцелярских формулировок.
- financial_terms / property_terms: короткие основы («ипотек», «квартир», «дом»,
  «участок», «студи», «маткапитал»).
- negative_keywords: признаки спама, аренды и продавцов-риелторов — то, что
  нужно отсеять («сдам», «аренда», «посуточно», «работа»).
- search_queries: наоборот, полноценные поисковые фразы С НАЗВАНИЕМ ГОРОДА,
  по которым ищут сами чаты и группы («Геленджик недвижимость чат»).
- Минимум по 5 элементов в каждом списке.

ВОЗВРАЩАЙ СТРОГО JSON БЕЗ MARKDOWN:
{"search_queries":{"telegram":[],"vk_groups":[]},
"city_variations":[],"intent_phrases":[],
"financial_terms":[],"property_terms":[],"negative_keywords":[]}
"""

USER_PROMPT_GEO_KEYWORDS = (
    "Город: {city_name}\n"
    "Регион (только для контекста, НЕ включай его в city_variations): {region}\n"
    "Тип рынка: {market_type}\nОсновные сегменты: {primary_segments}"
)
