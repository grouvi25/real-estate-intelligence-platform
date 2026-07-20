"""Unit tests for LM-2/3/4/6 calculators (TZ section 29). Pure, no DB/network."""
from __future__ import annotations

from app.services.lead_magnets import (
    districts,
    mortgage_calculator as mc,
    object_checker,
    roi_calculator as roi,
)


# --- LM-2: mortgage ---------------------------------------------------------

def test_annuity_zero_rate_is_linear():
    # 1.2M over 12 months at 0% -> 100k/mo.
    assert mc.annuity_payment(1_200_000, 0, 12) == 100_000


def test_annuity_positive_rate_exceeds_linear():
    linear = 1_000_000 / 120
    assert mc.annuity_payment(1_000_000, 12, 120) > linear


def test_matkapital_reduces_loan():
    without = mc.calculate_program("family", 6_000_000, 1_000_000, 20, "other", False)
    with_mk = mc.calculate_program("family", 6_000_000, 1_000_000, 20, "other", True)
    assert with_mk.loan_amount == without.loan_amount - mc.MATKAPITAL_2026
    assert with_mk.matkapital_applied == mc.MATKAPITAL_2026


def test_family_program_over_regional_limit_not_eligible():
    # 20M price, small down payment -> loan over the 6M "other" limit.
    r = mc.calculate_program("family", 20_000_000, 1_000_000, 20, "other", False)
    assert r.eligible is False
    assert any("лимит" in n for n in r.notes)


def test_low_down_payment_flagged():
    r = mc.calculate_program("base", 5_000_000, 100_000, 20, "other", False)
    assert r.eligible is False
    assert any("взнос" in n for n in r.notes)


def test_compare_orders_eligible_and_cheapest_first():
    results = mc.compare_programs(5_000_000, 1_500_000, 20, "other", False)
    assert len(results) == len(mc.MORTGAGE_PROGRAMS)
    eligible = [r for r in results if r.eligible]
    # eligible ones come first
    assert results[: len(eligible)] == eligible
    # cheapest eligible payment first
    payments = [r.monthly_payment for r in eligible]
    assert payments == sorted(payments)


# --- LM-6: ROI --------------------------------------------------------------

def test_roi_derives_rent_from_city_assumption():
    r = roi.calculate_roi(10_000_000, 50, "Москва")
    expected = int(round(roi.RENTAL_ASSUMPTIONS["Москва"]["rent_per_sqm"] * 50))
    assert r.monthly_rent == expected
    assert r.gross_yield_pct > 0
    assert r.payback_years > 0


def test_roi_unknown_city_uses_default_and_notes():
    r = roi.calculate_roi(5_000_000, 40, "Урюпинск")
    assert any("средни" in n.lower() for n in r.notes)
    assert r.deposit_rate_pct == round(roi.DEPOSIT_RATE * 100, 1)


def test_roi_explicit_rent_beats_deposit_verdict():
    # A very high rent should beat the deposit.
    r = roi.calculate_roi(3_000_000, 40, "Казань", monthly_rent=80_000)
    assert r.annual_net_income > r.deposit_annual_income
    assert r.verdict.startswith("Аренда выгоднее")


# --- LM-4: districts --------------------------------------------------------

def test_districts_rank_by_scenario_fit():
    recs = districts.recommend_districts("Москва", "young_family")
    assert recs
    # match_pct descending among affordable
    pcts = [r.match_pct for r in recs]
    assert pcts == sorted(pcts, reverse=True)
    assert all(isinstance(r.matched_priorities, list) for r in recs)


def test_districts_budget_marks_unaffordable_last():
    recs = districts.recommend_districts("Москва", "investor", budget_max=15_000_000, area_sqm=60)
    # unaffordable ones sink to the bottom
    affordable_flags = [r.affordable for r in recs]
    assert affordable_flags == sorted(affordable_flags, reverse=True)


def test_districts_unknown_city_empty():
    assert districts.recommend_districts("Атлантида", "investor") == []


# --- LM-3: object checker ---------------------------------------------------

def test_object_checker_blocks_cian():
    r = object_checker.check_object("https://www.cian.ru/sale/flat/123456/")
    assert r.auto_check_available is False
    assert r.platform == "ЦИАН"
    assert len(r.checklist) >= 5


def test_object_checker_blocks_avito_and_domclick():
    assert object_checker.check_object("https://avito.ru/x").platform == "Авито"
    assert object_checker.check_object("https://domclick.ru/y").platform == "ДомКлик"


def test_object_checker_checklist_always_present():
    r = object_checker.check_object("not-a-real-domain.example")
    assert r.checklist
    assert r.recommendation
