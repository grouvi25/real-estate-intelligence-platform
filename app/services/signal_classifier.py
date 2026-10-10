"""Signal category: покупка / аренда / новости / конкуренты / прочее. ТЗ «Сигналы» 6.

Deterministic keyword matching, no AI call (the ТЗ: too expensive for every
signal); a manager can correct a category by hand (PATCH /api/signals/{id}/category).

Order: a competitor's name first, then purchase, rental, news. The purchase words
of the ТЗ («куп», «ипотек», …) miss the commonest buyer phrasing -- «ищу квартиру
в Геленджике, бюджет 8 млн» has none of them -- so the list carries buyer phrases
too. The same words mark old signals in migration 066; keep the two in step.
"""
from __future__ import annotations

import time
import uuid
from typing import Optional

CATEGORIES = ("purchase", "rental", "news", "competitor", "other")
CATEGORY_RU = {"purchase": "Покупка", "rental": "Аренда", "news": "Новости",
               "competitor": "Конкуренты", "other": "Прочее"}

CATEGORY_KEYWORDS = {
    "purchase": ["куп", "продаж", "ипотек", "взнос", "рассрочк", "новостройк",
                 "ищу квартир", "ищу дом", "ищу участ", "присматрива", "рассматрива",
                 "подобрать", "подберите"],
    "rental": ["аренд", "сдам", "сдаю", "сниму", "снять", "посуточно"],
    "news": ["закон", "ставк", "цб рф", "льготн", "субсиди", "новост"],
}


def classify_category(text: str, competitor_names: Optional[list[str]] = None) -> str:
    low = (text or "").lower().replace("ё", "е")
    for name in competitor_names or []:
        name = (name or "").strip().lower().replace("ё", "е")
        if len(name) >= 3 and name in low:
            return "competitor"
    for category in ("purchase", "rental", "news"):
        if any(kw in low for kw in CATEGORY_KEYWORDS[category]):
            return category
    return "other"


# Competitor names change rarely and a collection run classifies hundreds of
# messages of the same agency: five minutes of cache per agency.
_CACHE: dict[str, tuple[float, list[str]]] = {}
CACHE_SECONDS = 300


async def competitor_names_for(session, agency_id) -> list[str]:
    from app.models.agency import Agency  # noqa: PLC0415
    from app.services.discovery.settings import competitor_names_of  # noqa: PLC0415

    key = str(agency_id)
    cached = _CACHE.get(key)
    if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1]
    try:
        agency = await session.get(Agency, uuid.UUID(key))
        names = competitor_names_of(agency) if agency is not None else []
    except Exception:  # noqa: BLE001 - no competitors is a category, not a failed collection
        names = []
    _CACHE[key] = (time.monotonic(), names)
    return names


def forget_competitors(agency_id) -> None:
    _CACHE.pop(str(agency_id), None)


async def category_for(session, agency_id, text: str) -> str:
    return classify_category(text, await competitor_names_for(session, agency_id))
