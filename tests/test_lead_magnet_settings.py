"""Lead magnets per agency: which tools are on, the agency's rates, the public
config the /lm pages read, and the owner's settings screen."""
import os
import uuid
from types import SimpleNamespace

import pytest

from app.exceptions import AppException

db_only = pytest.mark.skipif(os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL")


def _agency(settings=None, active=True, paid=True):
    return SimpleNamespace(settings=settings or {}, is_active=active, subscription_active=paid,
                           base_city="Геленджик")


def test_a_new_agency_has_every_tool_with_the_tz_figures():
    from app.services.lead_magnets import settings as lm

    agency = _agency()
    assert lm.enabled_slugs(agency) == lm.SLUGS
    assert lm.programs_for(agency)["standard"].rate == 0.18
    assert lm.rental_for(agency, "Геленджик")["season_months"] == 5.0


def test_switched_off_tools_and_own_rates_are_used():
    from app.services.lead_magnets import settings as lm

    agency = _agency({"lead_magnets": {"disabled": ["checker", "nonsense"],
                                       "mortgage_rates": {"standard": 0.21},
                                       "rental": {"occupancy": 0.5}}})
    assert "checker" not in lm.enabled_slugs(agency)
    assert lm.programs_for(agency)["standard"].rate == 0.21
    assert lm.programs_for(agency)["family"].rate == 0.06  # untouched programs keep the default
    rental = lm.rental_for(agency, "Геленджик")
    assert rental["occupancy"] == 0.5 and rental["season_months"] == 5.0


def test_a_blocked_agency_shows_no_tools():
    from app.services.lead_magnets import settings as lm

    assert lm.enabled_slugs(_agency(paid=False)) == []
    assert lm.enabled_slugs(_agency(active=False)) == []


def test_the_owner_cannot_save_nonsense():
    from app.services.lead_magnets import settings as lm

    with pytest.raises(AppException):
        lm.validate_update({}, enabled=["mortgage", "teleport"])
    with pytest.raises(AppException):
        lm.validate_update({}, mortgage_rates={"standard": 0.9})
    with pytest.raises(AppException) as err:
        lm.validate_update({}, rental={"occupancy": 1.5})
    assert "Загрузка" in err.value.detail  # said in the owner's words, not "occupancy"
    saved = lm.validate_update({}, enabled=["mortgage", "roi"])
    assert set(saved["disabled"]) == set(lm.SLUGS) - {"mortgage", "roi"}


def test_the_calculators_take_the_agency_figures():
    from app.services.lead_magnets import mortgage_calculator as mc
    from app.services.lead_magnets import roi_calculator as rc

    own = {k: v for k, v in mc.MORTGAGE_PROGRAMS.items()}
    own["standard"] = mc.MortgageProgram("Стандартная", 0.10, 30, "")
    cheaper = mc.calculate_mortgage(8_000_000, 2_000_000, 20, "standard", programs=own)
    default = mc.calculate_mortgage(8_000_000, 2_000_000, 20, "standard")
    assert cheaper["rate_percent"] == 10.0 and cheaper["monthly_payment"] < default["monthly_payment"]
    roi = rc.calculate_investment_roi(8_000_000, "Геленджик",
                                      assumptions={"season_months": 12, "rate_pct": 0.007, "occupancy": 1.0})
    assert roi["assumptions"]["season_months"] == 12


async def _new_agency(s, name="LM Settings"):
    from app.models.agency import Agency
    from app.models.manager import Manager

    from tests.helpers import unique_telegram_id

    agency = Agency(name=name, base_city="Геленджик")
    s.add(agency)
    await s.flush()
    owner = Manager(agency_id=agency.id, name="Владелец", role="owner",
                    telegram_id=unique_telegram_id(), is_active=True)
    manager = Manager(agency_id=agency.id, name="Менеджер", role="manager",
                      telegram_id=unique_telegram_id(), is_active=True)
    s.add_all([owner, manager])
    await s.commit()
    return agency, owner, manager


@db_only
@pytest.mark.asyncio
async def test_switching_a_tool_off_closes_its_page_and_its_api():
    from app.database import async_session, engine, run_migrations
    from app.dependencies import CurrentManager
    from app.routers.agency import LeadMagnetsRequest, get_lead_magnets, update_lead_magnets
    from app.routers.lead_magnets import (
        LM2CalcRequest,
        LM2SubscribeRequest,
        lm2_calculate,
        lm2_subscribe,
        lm_config,
    )
    from app.services.lead_magnets import settings as lm

    await run_migrations()
    try:
        async with async_session() as s:
            agency, owner, manager = await _new_agency(s)
            as_owner = CurrentManager(str(owner.id), str(agency.id))
            as_manager = CurrentManager(str(manager.id), str(agency.id))

            dto = await get_lead_magnets(current=as_owner, session=s)
            assert [t["slug"] for t in dto["tools"] if t["enabled"]] == [
                "finder", "mortgage", "checker", "districts", "market", "roi"]
            assert dto["tools"][1]["url"].endswith(f"/lm/{agency.id}/mortgage")

            with pytest.raises(AppException):  # a manager cannot change them
                await update_lead_magnets(LeadMagnetsRequest(enabled=["roi"]), current=as_manager, session=s)

            dto = await update_lead_magnets(LeadMagnetsRequest(
                enabled=["finder", "checker", "districts", "market", "roi"],
                mortgage_rates_percent={"standard": 21.5},
                rental={"season_months": 6, "monthly_rent_percent": 0.8, "occupancy_percent": 70}),
                current=as_owner, session=s)
            assert not next(t for t in dto["tools"] if t["slug"] == "mortgage")["enabled"]
            assert next(p for p in dto["mortgage_programs"] if p["key"] == "standard")["rate_percent"] == 21.5
            assert dto["rental"] == {"city": "Геленджик", "season_months": 6.0,
                                     "monthly_rent_percent": 0.8, "occupancy_percent": 70.0}

            cfg = await lm_config(agency.id, session=s)
            assert "mortgage" not in [t["slug"] for t in cfg["tools"]]
            assert cfg["agency"] == {"name": "LM Settings", "city": "Геленджик"}

            calc = LM2CalcRequest(property_price=8_000_000, down_payment=2_000_000, agency_id=agency.id)
            with pytest.raises(AppException) as err:
                await lm2_calculate(calc, session=s)
            assert err.value.status_code == 403
            with pytest.raises(AppException):
                await lm2_subscribe(LM2SubscribeRequest(
                    calc_data=calc, contact_phone="+79001112233", contact_name="Иван",
                    consent_given=True, consent_text="да", agency_id=agency.id), session=s)

            # back on: the page computes with the agency's 21.5 %
            await update_lead_magnets(LeadMagnetsRequest(enabled=list(lm.SLUGS)),
                                      current=as_owner, session=s)
            res = await lm2_calculate(calc, session=s)
            assert res["selected_program"]["rate_percent"] == 21.5
    finally:
        await engine.dispose()


@db_only
@pytest.mark.asyncio
async def test_a_request_from_a_page_is_counted_for_its_tool():
    from app.database import async_session, engine, run_migrations
    from app.dependencies import CurrentManager
    from app.routers.agency import get_lead_magnets
    from app.routers.lead_magnets import LM6CalcRequest, LM6SubscribeRequest, lm6_subscribe

    await run_migrations()
    try:
        async with async_session() as s:
            agency, owner, _ = await _new_agency(s, "LM Counter")
            res = await lm6_subscribe(LM6SubscribeRequest(
                calc_data=LM6CalcRequest(property_price=9_000_000, city="Геленджик"),
                contact_phone=f"+7900{uuid.uuid4().int % 10_000_000:07d}", contact_name="Олег",
                consent_given=True, consent_text="да", agency_id=agency.id), session=s)
            assert res["is_duplicate"] is False
            dto = await get_lead_magnets(current=CurrentManager(str(owner.id), str(agency.id)), session=s)
            assert next(t for t in dto["tools"] if t["slug"] == "roi")["leads_30d"] == 1
            assert next(t for t in dto["tools"] if t["slug"] == "mortgage")["leads_30d"] == 0
    finally:
        await engine.dispose()


def test_the_public_page_is_served_for_any_tool_path():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    for path in (f"/lm/{uuid.uuid4()}", f"/lm/{uuid.uuid4()}/mortgage"):
        r = client.get(path)
        assert r.status_code == 200 and "lm.js" in r.text
    assert client.get("/lm-assets/lm.js").status_code == 200
