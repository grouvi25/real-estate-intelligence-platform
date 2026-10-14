"""LM-2: mortgage calculator. TZ section 29.1 (exact spec).

5 programs (standard/family/it/military/rural), maternal capital 2026, annuity.
Pure functions, no DB/network — the router adds rate limiting + consent + dedup.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class MortgageProgram:
    name: str
    rate: float
    max_term_years: int
    description: str


MORTGAGE_PROGRAMS: dict[str, MortgageProgram] = {
    "standard": MortgageProgram("Стандартная", 0.18, 30, "Любой объект"),
    "family": MortgageProgram("Семейная", 0.06, 30, "Новостройка, дети до 18"),
    "it": MortgageProgram("IT-ипотека", 0.05, 30, "Новостройка до 18М, IT"),
    "military": MortgageProgram("Военная", 0.075, 25, "Военнослужащие"),
    "rural": MortgageProgram("Сельская", 0.03, 25, "Частный дом в селе"),
}

MATKAPITAL_2026 = 833_000


def annuity_payment(principal: float, annual_rate: float, term_months: int) -> float:
    if annual_rate == 0:
        return principal / term_months
    r = annual_rate / 12
    return principal * r * (1 + r) ** term_months / ((1 + r) ** term_months - 1)


def calculate_mortgage(
    property_price: int,
    down_payment: int,
    term_years: int,
    program_key: str = "standard",
    use_matkapital: bool = False,
    monthly_income: Optional[int] = None,
) -> dict:
    prog = MORTGAGE_PROGRAMS.get(program_key, MORTGAGE_PROGRAMS["standard"])
    eff_down = down_payment + (MATKAPITAL_2026 if use_matkapital else 0)
    if eff_down >= property_price:
        return {"error": "Первоначальный взнос >= стоимости объекта"}
    loan = property_price - eff_down
    term_m = min(term_years, prog.max_term_years) * 12
    monthly = annuity_payment(loan, prog.rate, term_m)
    total = monthly * term_m
    rec_income = monthly / 0.4
    return {
        "program": prog.name,
        "rate_percent": round(prog.rate * 100, 1),
        "loan_amount": int(loan),
        "down_payment_used": int(eff_down),
        "matkapital_used": MATKAPITAL_2026 if use_matkapital else 0,
        "term_years": term_m // 12,
        "monthly_payment": int(monthly),
        "total_payment": int(total),
        "overpayment": int(total - loan),
        "overpayment_percent": round((total - loan) / loan * 100, 1),
        "recommended_min_income": int(rec_income),
        "income_sufficient": monthly_income >= rec_income if monthly_income else None,
        "conditions": prog.description,
    }


def compare_programs(property_price: int, down_payment: int, term_years: int) -> list:
    results = []
    for key in MORTGAGE_PROGRAMS:
        c = calculate_mortgage(property_price, down_payment, term_years, key)
        c["program_key"] = key
        results.append(c)
    return sorted(results, key=lambda x: x.get("monthly_payment", 9_999_999))
