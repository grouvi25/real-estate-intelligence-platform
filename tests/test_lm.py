"""TZ section 33.2 acceptance tests for lead magnets (adapted to direct calls).

Mirrors the acceptance criteria in TZ 35.6: LM-2 calculate (5 programs), LM-2
subscribe consent gate (400), LM-6 calculate (deposit 16%), LM-3 blocked URL.
"""
from __future__ import annotations

import uuid

import pytest

from app.exceptions import ConsentRequiredError


@pytest.mark.asyncio
async def test_lm2_calculate():
    from app.routers.lead_magnets import LM2CalcRequest, lm2_calculate

    res = await lm2_calculate(LM2CalcRequest(
        property_price=8_000_000, down_payment=2_000_000, term_years=20, program="family"))
    assert res["selected_program"]["monthly_payment"] > 0
    assert len(res["all_programs"]) == 5


@pytest.mark.asyncio
async def test_lm2_no_consent():
    from app.routers.lead_magnets import LM2CalcRequest, LM2SubscribeRequest, lm2_subscribe

    req = LM2SubscribeRequest(
        calc_data=LM2CalcRequest(property_price=8_000_000, down_payment=2_000_000, term_years=20),
        contact_phone="+79001234567", contact_name="Тест",
        consent_given=False, consent_text="", agency_id=uuid.uuid4())
    with pytest.raises(ConsentRequiredError):
        await lm2_subscribe(req, session=None)


@pytest.mark.asyncio
async def test_lm6_calculate():
    from app.routers.lead_magnets import LM6CalcRequest, lm6_calculate

    data = await lm6_calculate(LM6CalcRequest(property_price=7_500_000, city="Геленджик"))
    assert "roi_rental_only_pct" in data
    assert data["vs_deposit"]["deposit_rate_pct"] == 16.0


@pytest.mark.asyncio
async def test_lm3_blocked_url():
    from app.routers.lead_magnets import LM3AnalyzeRequest, lm3_analyze

    res = await lm3_analyze(LM3AnalyzeRequest(
        listing_url="https://cian.ru/sale/flat/123/", city="Геленджик"))
    assert res["needs_manual_text"] is True
