"""LM-2: mortgage calculator. TZ section 29.2.

Pure functions: annuity payment + program comparison for the 2026 Russian
mortgage market. Maternal capital (материнский капитал) can be added to the down
payment. No database or network access, so it is trivially unit testable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# Материнский капитал на 2026 (индексация, ~833 000 ₽ на второго ребёнка).
MATKAPITAL_2026 = 833_000

# Государственные и рыночные ипотечные программы (условия на 2026 год).
# max_amount: региональные лимиты. "msk_spb" — Москва/МО и СПб/ЛО, "other" —
# остальные регионы, "default" — единый лимит.
MORTGAGE_PROGRAMS: dict[str, dict] = {
    "family": {
        "name": "Семейная ипотека",
        "rate": 6.0,
        "max_amount": {"msk_spb": 12_000_000, "other": 6_000_000},
        "min_down_payment_pct": 20.0,
        "max_term_years": 30,
        "conditions": "Семьи с ребёнком до 6 лет или с двумя несовершеннолетними детьми",
    },
    "it": {
        "name": "IT-ипотека",
        "rate": 6.0,
        "max_amount": {"default": 9_000_000},
        "min_down_payment_pct": 20.0,
        "max_term_years": 30,
        "conditions": "Сотрудники аккредитованных IT-компаний (кроме Москвы и СПб)",
    },
    "far_east": {
        "name": "Дальневосточная и арктическая ипотека",
        "rate": 2.0,
        "max_amount": {"default": 9_000_000},
        "min_down_payment_pct": 20.0,
        "max_term_years": 20,
        "conditions": "Молодые семьи и участники программ ДФО и Арктической зоны",
    },
    "rural": {
        "name": "Сельская ипотека",
        "rate": 3.0,
        "max_amount": {"default": 6_000_000},
        "min_down_payment_pct": 20.0,
        "max_term_years": 25,
        "conditions": "Покупка или строительство жилья в сельской местности",
    },
    "base": {
        "name": "Базовая (рыночная) ипотека",
        "rate": 22.0,
        "max_amount": {"default": 100_000_000},
        "min_down_payment_pct": 15.0,
        "max_term_years": 30,
        "conditions": "Без государственных льгот, стандартные условия банка",
    },
}


@dataclass
class MortgageResult:
    program: str
    program_name: str
    eligible: bool
    rate: float
    price: int
    down_payment: int
    matkapital_applied: int
    loan_amount: int
    term_years: int
    monthly_payment: int
    total_paid: int
    overpayment: int
    required_income: int
    notes: list[str] = field(default_factory=list)


def annuity_payment(principal: float, annual_rate_pct: float, term_months: int) -> float:
    """Standard annuity (equal monthly) payment."""
    if term_months <= 0:
        return principal
    if annual_rate_pct <= 0:
        return principal / term_months
    r = annual_rate_pct / 100 / 12
    factor = (1 + r) ** term_months
    return principal * r * factor / (factor - 1)


def _max_amount_for(program: dict, region: str) -> int:
    limits = program["max_amount"]
    if "default" in limits:
        return limits["default"]
    key = "msk_spb" if region == "msk_spb" else "other"
    return limits.get(key, limits.get("other", 0))


def calculate_program(
    program: str,
    price: int,
    down_payment: int,
    term_years: int,
    region: str = "other",
    use_matkapital: bool = False,
) -> MortgageResult:
    """Compute the payment schedule for a single program.

    The result is still returned when the request violates a program limit
    (eligible=False + explanatory notes) so the UI can show why a program does
    not fit rather than hiding it.
    """
    prog = MORTGAGE_PROGRAMS[program]
    notes: list[str] = []
    eligible = True

    matkapital = MATKAPITAL_2026 if use_matkapital else 0
    effective_down = down_payment + matkapital
    loan = max(price - effective_down, 0)

    term_years = min(term_years, prog["max_term_years"])
    if term_years <= 0:
        term_years = 1

    max_loan = _max_amount_for(prog, region)
    if loan > max_loan:
        eligible = False
        notes.append(
            f"Сумма кредита {loan:,} ₽ превышает лимит программы {max_loan:,} ₽".replace(",", " ")
        )

    down_pct = (effective_down / price * 100) if price else 0
    if down_pct < prog["min_down_payment_pct"]:
        eligible = False
        notes.append(
            f"Первоначальный взнос {down_pct:.0f}% ниже минимального "
            f"{prog['min_down_payment_pct']:.0f}%"
        )

    months = term_years * 12
    monthly = annuity_payment(loan, prog["rate"], months)
    total_paid = monthly * months + effective_down
    overpayment = monthly * months - loan
    # Банки одобряют кредит, если платёж <= 50% дохода.
    required_income = monthly * 2

    if matkapital:
        notes.append(f"Учтён материнский капитал {matkapital:,} ₽".replace(",", " "))

    return MortgageResult(
        program=program,
        program_name=prog["name"],
        eligible=eligible,
        rate=prog["rate"],
        price=price,
        down_payment=down_payment,
        matkapital_applied=matkapital,
        loan_amount=int(round(loan)),
        term_years=term_years,
        monthly_payment=int(round(monthly)),
        total_paid=int(round(total_paid)),
        overpayment=int(round(overpayment)),
        required_income=int(round(required_income)),
        notes=notes,
    )


def compare_programs(
    price: int,
    down_payment: int,
    term_years: int,
    region: str = "other",
    use_matkapital: bool = False,
    programs: Optional[list[str]] = None,
) -> list[MortgageResult]:
    """Calculate every requested program; eligible ones first, cheapest first."""
    names = programs or list(MORTGAGE_PROGRAMS.keys())
    results = [
        calculate_program(p, price, down_payment, term_years, region, use_matkapital)
        for p in names
        if p in MORTGAGE_PROGRAMS
    ]
    results.sort(key=lambda r: (not r.eligible, r.monthly_payment))
    return results
