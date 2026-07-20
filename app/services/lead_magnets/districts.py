"""LM-4: district recommender by life scenario. TZ section 29.4.

Maps a buyer's life scenario to district characteristics and ranks districts
within a city by fit + budget. Data-driven, pure functions.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Жизненные сценарии → приоритеты (теги инфраструктуры).
LIFE_SCENARIOS: dict[str, dict] = {
    "young_family": {
        "name": "Молодая семья с детьми",
        "priorities": ["schools", "kindergartens", "parks", "safety", "clinics"],
    },
    "investor": {
        "name": "Инвестор",
        "priorities": ["liquidity", "transport", "business", "price_growth"],
    },
    "professional": {
        "name": "Работающий профессионал",
        "priorities": ["transport", "business", "restaurants", "fitness"],
    },
    "retiree": {
        "name": "Спокойная жизнь / для родителей",
        "priorities": ["parks", "clinics", "quiet", "ecology"],
    },
    "student": {
        "name": "Студент / первое жильё",
        "priorities": ["transport", "universities", "price_low", "restaurants"],
    },
}

# Районы по городам. tags — сильные стороны района.
DISTRICTS: dict[str, list[dict]] = {
    "Москва": [
        {"name": "Хамовники", "avg_price_sqm": 550_000,
         "tags": ["parks", "schools", "safety", "restaurants", "clinics"]},
        {"name": "Раменки", "avg_price_sqm": 380_000,
         "tags": ["schools", "kindergartens", "parks", "universities", "transport"]},
        {"name": "Марьино", "avg_price_sqm": 250_000,
         "tags": ["price_low", "transport", "parks", "safety"]},
        {"name": "Пресненский (Москва-Сити)", "avg_price_sqm": 500_000,
         "tags": ["business", "transport", "liquidity", "restaurants", "fitness"]},
        {"name": "Некрасовка", "avg_price_sqm": 220_000,
         "tags": ["price_low", "kindergartens", "schools", "price_growth"]},
        {"name": "Коммунарка (Новая Москва)", "avg_price_sqm": 240_000,
         "tags": ["price_growth", "kindergartens", "schools", "clinics", "liquidity"]},
    ],
    "Санкт-Петербург": [
        {"name": "Центральный", "avg_price_sqm": 340_000,
         "tags": ["restaurants", "business", "transport", "liquidity"]},
        {"name": "Приморский", "avg_price_sqm": 250_000,
         "tags": ["parks", "schools", "kindergartens", "safety", "transport"]},
        {"name": "Московский", "avg_price_sqm": 260_000,
         "tags": ["transport", "business", "clinics", "liquidity"]},
        {"name": "Мурино (ЛО)", "avg_price_sqm": 180_000,
         "tags": ["price_low", "price_growth", "kindergartens", "transport"]},
    ],
    "Казань": [
        {"name": "Вахитовский", "avg_price_sqm": 230_000,
         "tags": ["business", "restaurants", "transport", "liquidity", "universities"]},
        {"name": "Ново-Савиновский", "avg_price_sqm": 170_000,
         "tags": ["schools", "kindergartens", "parks", "safety"]},
        {"name": "Советский", "avg_price_sqm": 150_000,
         "tags": ["price_low", "transport", "clinics", "price_growth"]},
    ],
}


@dataclass
class DistrictRecommendation:
    name: str
    avg_price_sqm: int
    match_pct: int
    matched_priorities: list[str]
    affordable: bool
    notes: list[str] = field(default_factory=list)


# Человекочитаемые названия тегов для UI.
TAG_LABELS = {
    "schools": "школы", "kindergartens": "детские сады", "parks": "парки",
    "safety": "безопасность", "clinics": "медицина", "liquidity": "ликвидность",
    "transport": "транспорт", "business": "бизнес-центры", "price_growth": "рост цен",
    "restaurants": "рестораны", "fitness": "фитнес", "quiet": "тишина",
    "ecology": "экология", "universities": "вузы", "price_low": "низкая цена",
}


def recommend_districts(
    city: str,
    scenario: str,
    budget_max: int | None = None,
    area_sqm: float | None = None,
) -> list[DistrictRecommendation]:
    """Rank a city's districts by how well they fit a life scenario + budget."""
    scenario_def = LIFE_SCENARIOS.get(scenario, LIFE_SCENARIOS["young_family"])
    priorities = scenario_def["priorities"]
    districts = DISTRICTS.get(city, [])

    recs: list[DistrictRecommendation] = []
    for d in districts:
        matched = [p for p in priorities if p in d["tags"]]
        match_pct = int(round(len(matched) / len(priorities) * 100)) if priorities else 0

        affordable = True
        notes: list[str] = []
        if budget_max and area_sqm:
            est_price = d["avg_price_sqm"] * area_sqm
            if est_price > budget_max:
                affordable = False
                notes.append(
                    f"Оценка {int(est_price):,} ₽ выше бюджета {budget_max:,} ₽".replace(",", " ")
                )

        recs.append(
            DistrictRecommendation(
                name=d["name"],
                avg_price_sqm=d["avg_price_sqm"],
                match_pct=match_pct,
                matched_priorities=[TAG_LABELS.get(p, p) for p in matched],
                affordable=affordable,
                notes=notes,
            )
        )

    recs.sort(key=lambda r: (not r.affordable, -r.match_pct, r.avg_price_sqm))
    return recs
