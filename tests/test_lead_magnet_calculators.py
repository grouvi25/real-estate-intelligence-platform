"""Unit tests for LM-2/3/4/6 calculators (TZ section 29). Pure, no DB."""
from __future__ import annotations

import pytest

from app.services.lead_magnets import (
    districts,
    mortgage_calculator as mc,
    object_checker,
    roi_calculator as roi,
)


# --- LM-2: mortgage (TZ 29.1) ----------------------------------------------

def test_five_programs_defined():
    assert set(mc.MORTGAGE_PROGRAMS) == {"standard", "family", "it", "military", "rural"}
    assert mc.MATKAPITAL_2026 == 833_000


def test_annuity_zero_rate_is_linear():
    assert mc.annuity_payment(1_200_000, 0, 12) == 100_000


def test_calculate_mortgage_family():
    r = mc.calculate_mortgage(8_000_000, 2_000_000, 20, "family")
    assert r["program"] == "Семейная"
    assert r["rate_percent"] == 6.0
    assert r["loan_amount"] == 6_000_000
    assert r["monthly_payment"] > 0
    assert r["overpayment"] > 0


def test_matkapital_increases_effective_down_payment():
    without = mc.calculate_mortgage(8_000_000, 2_000_000, 20, "family", use_matkapital=False)
    with_mk = mc.calculate_mortgage(8_000_000, 2_000_000, 20, "family", use_matkapital=True)
    assert with_mk["matkapital_used"] == mc.MATKAPITAL_2026
    assert with_mk["loan_amount"] == without["loan_amount"] - mc.MATKAPITAL_2026


def test_down_payment_over_price_returns_error():
    r = mc.calculate_mortgage(3_000_000, 3_000_000, 20, "standard")
    assert "error" in r


def test_compare_programs_returns_five_sorted():
    results = mc.compare_programs(8_000_000, 2_000_000, 20)
    assert len(results) == 5
    payments = [r["monthly_payment"] for r in results]
    assert payments == sorted(payments)


# --- LM-6: ROI (TZ 29.4) ----------------------------------------------------

def test_roi_gelendzhik():
    r = roi.calculate_investment_roi(7_500_000, "Геленджик")
    assert "roi_rental_only_pct" in r
    assert r["vs_deposit"]["deposit_rate_pct"] == 16.0
    assert r["assumptions"]["season_months"] == 5.0


def test_roi_unknown_city_uses_default():
    r = roi.calculate_investment_roi(5_000_000, "Урюпинск")
    assert r["assumptions"]["season_months"] == roi.RENTAL_ASSUMPTIONS["default"]["season_months"]


# --- LM-4: districts (TZ 29.3) ---------------------------------------------

def test_life_scenarios_keys():
    assert set(districts.LIFE_SCENARIOS) == {
        "family", "investor", "relocant", "remote", "senior", "vacationer"}
    assert "JSON" in districts.SYSTEM_PROMPT_DISTRICTS


def test_fallback_districts_shape():
    out = districts.fallback_districts("Геленджик", "family")
    assert out["ai_used"] is False
    assert isinstance(out["districts"], list)


# --- LM-3: object checker (TZ 29.2) ----------------------------------------

@pytest.mark.asyncio
async def test_fetch_blocked_cian_returns_manual():
    ok, msg = await object_checker.fetch_listing_text("https://www.cian.ru/sale/flat/123/")
    assert ok is False
    assert "вручную" in msg


@pytest.mark.asyncio
async def test_fetch_blocked_avito_and_domclick():
    for host in ("https://avito.ru/x", "https://domclick.ru/y"):
        ok, _ = await object_checker.fetch_listing_text(host)
        assert ok is False
