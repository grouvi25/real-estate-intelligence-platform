"""Per-agency lead magnet settings: which tools are on, the agency's own mortgage
rates and rental assumptions.

Stored in ``agencies.settings["lead_magnets"]`` (no table of its own: the same
place the competitor names live). Only what the owner changed is stored; the
rest falls back to the defaults in the calculators, so a new agency gets every
tool on with the TZ figures.
"""
from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Any, Optional

from app.exceptions import AppException, NotFoundError
from app.services.lead_magnets import mortgage_calculator, roi_calculator

SETTINGS_KEY = "lead_magnets"

# slug in the public link, lm_source written on the lead, title, one line about it
TOOLS: list[tuple[str, str, str, str]] = [
    ("finder", "lm1_finder", "Подбор квартиры",
     "Человек описывает, что ищет, и получает варианты из вашего каталога"),
    ("mortgage", "lm2_mortgage", "Ипотечный калькулятор",
     "Платёж и переплата по пяти программам, с маткапиталом"),
    ("checker", "lm3_checker", "Проверка объявления",
     "ИИ разбирает чужое объявление: плюсы, минусы, риски"),
    ("districts", "lm4_districts", "Район под образ жизни",
     "Три района города под сценарий: семья, инвестиции, переезд…"),
    ("market", "lm5_market_report", "Отчёт по рынку",
     "Персональный обзор цен и спроса под бюджет и цель"),
    ("roi", "lm6_roi", "Доходность для инвестора",
     "Сезонная аренда против вклада: окупаемость и доход"),
]
# What the client reads on the public page (the lines above are for the owner).
CLIENT_DESCRIPTION = {
    "finder": "Назовите бюджет и цель — подберём квартиры из каталога агентства",
    "mortgage": "Платёж и переплата по пяти программам, с маткапиталом",
    "checker": "Пришлите чужое объявление — разберём плюсы, минусы и риски",
    "districts": "Три района под ваш образ жизни: семья, инвестиции, переезд",
    "market": "Цены, спрос и подводные камни под ваш бюджет",
    "roi": "Сколько принесёт сдача в аренду по сравнению со вкладом",
}
SLUGS = [t[0] for t in TOOLS]
SOURCE_BY_SLUG = {slug: source for slug, source, _, _ in TOOLS}

# what the owner may set, with sane bounds
RATE_MIN, RATE_MAX = 0.0, 0.5
RENTAL_BOUNDS = {"season_months": (0.5, 12.0), "rate_pct": (0.0005, 0.05), "occupancy": (0.05, 1.0)}
# how the owner sees them: label and the scale from stored value to shown value
RENTAL_LABELS = {"season_months": ("Сезон, месяцев", 1), "rate_pct": ("Аренда в месяц сезона, % от цены", 100),
                 "occupancy": ("Загрузка в сезон, %", 100)}


def stored(agency) -> dict:
    return dict(((agency.settings if agency else None) or {}).get(SETTINGS_KEY) or {})


def disabled(agency) -> set[str]:
    return {s for s in stored(agency).get("disabled") or [] if s in SLUGS}


def is_available(agency) -> bool:
    """A blocked or deactivated agency shows no tools at all."""
    return bool(agency and agency.is_active and agency.subscription_active)


def enabled_slugs(agency) -> list[str]:
    if not is_available(agency):
        return []
    off = disabled(agency)
    return [s for s in SLUGS if s not in off]


def programs_for(agency) -> dict[str, mortgage_calculator.MortgageProgram]:
    rates = stored(agency).get("mortgage_rates") or {}
    out = {}
    for key, prog in mortgage_calculator.MORTGAGE_PROGRAMS.items():
        rate = rates.get(key)
        out[key] = replace(prog, rate=float(rate)) if isinstance(rate, (int, float)) else prog
    return out


def rental_for(agency, city: str) -> dict[str, float]:
    base = roi_calculator.RENTAL_ASSUMPTIONS.get(city, roi_calculator.RENTAL_ASSUMPTIONS["default"])
    own = stored(agency).get("rental") or {}
    return {k: float(own[k]) if isinstance(own.get(k), (int, float)) else v for k, v in base.items()}


def validate_update(current: dict, enabled: Optional[list[str]] = None,
                    mortgage_rates: Optional[dict[str, Any]] = None,
                    rental: Optional[dict[str, Any]] = None) -> dict:
    """The new stored settings, or AppException(400) with what is wrong."""
    out = dict(current)
    if enabled is not None:
        unknown = set(enabled) - set(SLUGS)
        if unknown:
            raise AppException(400, f"неизвестный инструмент: {', '.join(sorted(unknown))}", "LM_UNKNOWN")
        out["disabled"] = [s for s in SLUGS if s not in set(enabled)]
    if mortgage_rates is not None:
        rates = {}
        for key, value in mortgage_rates.items():
            if key not in mortgage_calculator.MORTGAGE_PROGRAMS:
                raise AppException(400, f"неизвестная программа: {key}", "LM_UNKNOWN")
            if not isinstance(value, (int, float)) or not RATE_MIN <= value <= RATE_MAX:
                raise AppException(400, "ставка — от 0 до 50 %", "LM_BAD_RATE")
            rates[key] = round(float(value), 4)
        out["mortgage_rates"] = rates
    if rental is not None:
        clean = {}
        for key, value in rental.items():
            low, high = RENTAL_BOUNDS.get(key, (None, None))
            if low is None:
                raise AppException(400, f"неизвестный параметр: {key}", "LM_UNKNOWN")
            if not isinstance(value, (int, float)) or not low <= value <= high:
                label, scale = RENTAL_LABELS[key]
                raise AppException(400, f"{label}: от {low * scale:g} до {high * scale:g}", "LM_BAD_VALUE")
            clean[key] = round(float(value), 4)
        out["rental"] = clean
    return out


async def require_enabled(session, agency_id: uuid.UUID, slug: str):
    """The agency, when ``slug`` is on for it; 404 / 403 otherwise."""
    from app.models.agency import Agency  # noqa: PLC0415

    agency = await session.get(Agency, agency_id)
    if agency is None:
        raise NotFoundError("Agency", str(agency_id))
    if slug not in enabled_slugs(agency):
        raise AppException(403, "Этот инструмент сейчас выключен агентством", "LM_DISABLED")
    return agency
