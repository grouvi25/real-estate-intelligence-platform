"""LM-6: investor ROI calculator. TZ section 29.4 (exact spec).

Seasonal rental economics for Black Sea coast cities vs a bank deposit. Pure.
"""
from __future__ import annotations

from typing import Optional

RENTAL_ASSUMPTIONS = {
    "Геленджик": {"season_months": 5.0, "rate_pct": 0.007, "occupancy": 0.75},
    "Сочи": {"season_months": 9.0, "rate_pct": 0.009, "occupancy": 0.80},
    "Новороссийск": {"season_months": 3.5, "rate_pct": 0.005, "occupancy": 0.65},
    "Анапа": {"season_months": 4.5, "rate_pct": 0.006, "occupancy": 0.70},
    "default": {"season_months": 4.0, "rate_pct": 0.006, "occupancy": 0.70},
}
DEPOSIT_RATE = 0.16   # ставка по вкладу 2026
APPRECIATION = 0.05   # консервативный прирост стоимости в год


def calculate_investment_roi(
    property_price: int,
    city: str,
    down_payment: Optional[int] = None,
    renovation_budget: int = 0,
    monthly_expenses: int = 5_000,
) -> dict:
    a = RENTAL_ASSUMPTIONS.get(city, RENTAL_ASSUMPTIONS["default"])
    total = property_price + renovation_budget
    monthly_rental = property_price * a["rate_pct"]
    annual_gross = monthly_rental * a["season_months"] * a["occupancy"]
    annual_net = annual_gross - monthly_expenses * 12
    roi_rental = annual_net / total * 100
    payback = total / annual_net if annual_net > 0 else 999
    deposit_base = down_payment or property_price
    deposit_income = deposit_base * DEPOSIT_RATE
    total_return = annual_net + property_price * APPRECIATION
    return {
        "city": city,
        "property_price": property_price,
        "total_investment": total,
        "assumptions": {
            "season_months": a["season_months"],
            "occupancy_pct": int(a["occupancy"] * 100),
            "monthly_rental_estimate": int(monthly_rental),
        },
        "rental_income": {
            "annual_gross": int(annual_gross),
            "annual_expenses": int(monthly_expenses * 12),
            "annual_net": int(annual_net),
        },
        "roi_rental_only_pct": round(roi_rental, 1),
        "roi_with_appreciation_pct": round(total_return / total * 100, 1),
        "payback_years": round(payback, 1),
        "vs_deposit": {
            "deposit_amount": deposit_base,
            "deposit_rate_pct": DEPOSIT_RATE * 100,
            "deposit_annual_income": int(deposit_income),
            "real_estate_advantage": int(total_return - deposit_income),
            "verdict": "Недвижимость выгоднее депозита"
            if total_return > deposit_income
            else "Депозит выгоднее при данных параметрах",
        },
        "note": "Расчёт оценочный. Реальные показатели зависят от объекта и управления.",
    }
