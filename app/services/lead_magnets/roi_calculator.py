"""LM-6: rental ROI calculator. TZ section 29.6.

Estimates rental yield, payback period and compares the investment against a
bank deposit at the current key-rate-driven deposit rate. Pure functions.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Ставка по банковскому вкладу для сравнения (при ключевой ставке ~16%).
DEPOSIT_RATE = 0.16

# Допущения по аренде: средняя ставка аренды за м²/мес и заполняемость.
RENTAL_ASSUMPTIONS: dict[str, dict] = {
    "Москва": {"rent_per_sqm": 1200, "occupancy": 0.92, "annual_growth": 0.07},
    "Санкт-Петербург": {"rent_per_sqm": 900, "occupancy": 0.90, "annual_growth": 0.06},
    "Казань": {"rent_per_sqm": 650, "occupancy": 0.88, "annual_growth": 0.06},
    "Екатеринбург": {"rent_per_sqm": 600, "occupancy": 0.88, "annual_growth": 0.05},
    "Новосибирск": {"rent_per_sqm": 580, "occupancy": 0.87, "annual_growth": 0.05},
    "Сочи": {"rent_per_sqm": 1500, "occupancy": 0.80, "annual_growth": 0.09},
    "default": {"rent_per_sqm": 500, "occupancy": 0.85, "annual_growth": 0.05},
}

# Доля дохода, уходящая на налоги, управление, простой и текущий ремонт.
EXPENSE_RATIO = 0.15


@dataclass
class RoiResult:
    city: str
    price: int
    area_sqm: float
    monthly_rent: int
    occupancy: float
    annual_gross_income: int
    annual_net_income: int
    gross_yield_pct: float
    net_yield_pct: float
    payback_years: float
    deposit_annual_income: int
    deposit_rate_pct: float
    verdict: str
    notes: list[str] = field(default_factory=list)


def calculate_roi(
    price: int,
    area_sqm: float,
    city: str,
    monthly_rent: int | None = None,
) -> RoiResult:
    """Estimate rental economics for a property.

    monthly_rent may be provided (a known asking rent); otherwise it is derived
    from the per-m² assumption for the city.
    """
    assumptions = RENTAL_ASSUMPTIONS.get(city, RENTAL_ASSUMPTIONS["default"])
    notes: list[str] = []

    if monthly_rent is None or monthly_rent <= 0:
        monthly_rent = int(round(assumptions["rent_per_sqm"] * area_sqm))
        notes.append("Аренда рассчитана по средней ставке за м² в городе")
    if city not in RENTAL_ASSUMPTIONS:
        notes.append("Для города нет точных данных — использованы средние значения")

    occupancy = assumptions["occupancy"]
    gross_income = monthly_rent * 12 * occupancy
    net_income = gross_income * (1 - EXPENSE_RATIO)

    gross_yield = (gross_income / price * 100) if price else 0
    net_yield = (net_income / price * 100) if price else 0
    payback = (price / net_income) if net_income else 0

    deposit_income = price * DEPOSIT_RATE

    if net_income > deposit_income:
        verdict = "Аренда выгоднее вклада"
    elif net_yield >= DEPOSIT_RATE * 100 * 0.7:
        verdict = "Сопоставимо с вкладом, но есть рост стоимости актива"
    else:
        verdict = "Вклад выгоднее по текущему денежному потоку"

    return RoiResult(
        city=city,
        price=price,
        area_sqm=area_sqm,
        monthly_rent=int(round(monthly_rent)),
        occupancy=occupancy,
        annual_gross_income=int(round(gross_income)),
        annual_net_income=int(round(net_income)),
        gross_yield_pct=round(gross_yield, 2),
        net_yield_pct=round(net_yield, 2),
        payback_years=round(payback, 1),
        deposit_annual_income=int(round(deposit_income)),
        deposit_rate_pct=round(DEPOSIT_RATE * 100, 1),
        verdict=verdict,
        notes=notes,
    )
