"""Fixes for the reachability gaps left in docs/audit.md (need PostgreSQL).

Three items that each looked harmless on their own:
  * rematch_on_price_change only honoured buyer_profile exclusions, so a property
    the manager had rejected from the UI came back on a price drop;
  * POST /api/geo answers a partner-covered city with 202 and
    "action": "POST /api/partners/accept" -- an endpoint that did not exist, so
    the city could never be opened;
  * signals and properties had no GET /{id}, so detail screens pulled a 200-row
    list and searched it client-side.
"""
import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL"
)


async def _agency(s, name="Leftovers Agency"):
    from app.models.agency import Agency

    a = Agency(name=name, base_city="Геленджик")
    s.add(a)
    await s.flush()
    return a


def _current(agency):
    from app.dependencies import CurrentManager

    return CurrentManager(manager_id=str(uuid.uuid4()), agency_id=str(agency.id))


# --- 1. Price-drop re-match must honour table exclusions ---------------------

@pytest.mark.asyncio
async def test_rematch_skips_a_property_rejected_from_the_ui():
    from app.database import async_session, run_migrations
    from app.models.lead import Lead
    from app.models.match import LeadPropertyMatch
    from app.models.match_exclusion import MatchExclusion
    from app.models.property import Property
    from app.services.matching import MatchingEngine
    from sqlalchemy import select

    await run_migrations()
    async with async_session() as s:
        agency = await _agency(s)
        lead = Lead(agency_id=agency.id, source_type="signal", budget_max=9_000_000,
                    status="new", urgency="hot")
        prop = Property(agency_id=agency.id, title="Квартира", price=8_500_000, status="active")
        s.add_all([lead, prop])
        await s.flush()
        # The manager rejected it from the UI: that writes match_exclusions.
        s.add(MatchExclusion(agency_id=agency.id, lead_id=lead.id,
                             property_id=prop.id, category="location"))
        await s.commit()
        lead_id, prop_id = lead.id, prop.id

    touched = await MatchingEngine.rematch_on_price_change(
        str(prop_id), old_price=9_500_000, new_price=8_500_000)
    assert touched == 0

    async with async_session() as s:
        match = await s.scalar(
            select(LeadPropertyMatch).where(
                LeadPropertyMatch.lead_id == lead_id,
                LeadPropertyMatch.property_id == prop_id,
            )
        )
    assert match is None


@pytest.mark.asyncio
async def test_rematch_still_offers_a_property_that_was_never_rejected():
    """Guard against over-filtering: the feature must keep working."""
    from app.database import async_session, run_migrations
    from app.models.lead import Lead
    from app.models.property import Property
    from app.services.matching import MatchingEngine

    await run_migrations()
    async with async_session() as s:
        agency = await _agency(s, "Rematch Agency")
        lead = Lead(agency_id=agency.id, source_type="signal", budget_max=9_000_000,
                    status="new", urgency="hot")
        prop = Property(agency_id=agency.id, title="Другая квартира", price=8_500_000,
                        status="active")
        s.add_all([lead, prop])
        await s.commit()
        prop_id = prop.id

    touched = await MatchingEngine.rematch_on_price_change(
        str(prop_id), old_price=9_500_000, new_price=8_500_000)
    assert touched == 1


# --- 2. Accepting a partner-covered city ------------------------------------

@pytest.mark.asyncio
async def test_accept_partner_geo_opens_the_city_in_referral_mode(monkeypatch):
    from app.database import async_session, run_migrations
    from app.models.geo_location import GeoLocation
    from app.models.partner_agency import PartnerAgency
    from app.routers.partners import AcceptPartnerGeoRequest, accept_partner_geo

    import worker.tasks.geo_tasks as gt
    monkeypatch.setattr(gt.generate_keywords_for_geo, "delay", lambda *a, **k: None)

    await run_migrations()
    async with async_session() as s:
        agency = await _agency(s, "Accept Agency")
        partner = PartnerAgency(agency_id=agency.id, partner_name="Партнёр Сочи",
                                partner_city="Сочи", is_active=True)
        s.add(partner)
        await s.commit()
        current, partner_id = _current(agency), partner.id

    async with async_session() as s:
        res = await accept_partner_geo(
            AcceptPartnerGeoRequest(partner_id=partner_id, city_name="Сочи",
                                    region="Краснодарский край", market_type="resort"),
            current=current, session=s)

    assert res["status"] == "partner_mode"
    assert res["partner_name"] == "Партнёр Сочи"

    async with async_session() as s:
        geo = await s.get(GeoLocation, uuid.UUID(res["geo_id"]))
    assert geo.geo_type == "partner"
    assert geo.partner_agency_id == partner_id
    assert geo.auto_discovery_enabled is True


@pytest.mark.asyncio
async def test_accept_partner_geo_rejects_unknown_disabled_and_duplicate(monkeypatch):
    from app.database import async_session, run_migrations
    from app.exceptions import NotFoundError, ValidationError
    from app.models.partner_agency import PartnerAgency
    from app.routers.partners import AcceptPartnerGeoRequest, accept_partner_geo

    import worker.tasks.geo_tasks as gt
    monkeypatch.setattr(gt.generate_keywords_for_geo, "delay", lambda *a, **k: None)

    await run_migrations()
    async with async_session() as s:
        agency = await _agency(s, "Accept Guard Agency")
        active = PartnerAgency(agency_id=agency.id, partner_name="Активный",
                               partner_city="Сочи", is_active=True)
        disabled = PartnerAgency(agency_id=agency.id, partner_name="Отключённый",
                                 partner_city="Анапа", is_active=False)
        s.add_all([active, disabled])
        await s.commit()
        current = _current(agency)
        active_id, disabled_id = active.id, disabled.id

    async with async_session() as s:
        with pytest.raises(NotFoundError):
            await accept_partner_geo(
                AcceptPartnerGeoRequest(partner_id=uuid.uuid4(), city_name="Сочи"),
                current=current, session=s)
        with pytest.raises(ValidationError):
            await accept_partner_geo(
                AcceptPartnerGeoRequest(partner_id=disabled_id, city_name="Анапа"),
                current=current, session=s)

        await accept_partner_geo(
            AcceptPartnerGeoRequest(partner_id=active_id, city_name="Сочи"),
            current=current, session=s)

    async with async_session() as s:
        with pytest.raises(ValidationError):
            await accept_partner_geo(
                AcceptPartnerGeoRequest(partner_id=active_id, city_name="Сочи"),
                current=current, session=s)


# --- 3. Single-item endpoints ------------------------------------------------

@pytest.mark.asyncio
async def test_get_signal_and_property_by_id_are_agency_scoped():
    from app.database import async_session, run_migrations
    from app.exceptions import NotFoundError
    from app.models.property import Property
    from app.models.signal import Signal
    from app.routers.properties import get_property
    from app.routers.signals import get_signal

    await run_migrations()
    async with async_session() as s:
        agency = await _agency(s, "Detail Agency")
        other = await _agency(s, "Other Detail Agency")
        signal = Signal(agency_id=agency.id, raw_text="Куплю квартиру в Геленджике",
                        intent_score=85, urgency="hot")
        prop = Property(agency_id=agency.id, title="Студия", price=5_000_000)
        s.add_all([signal, prop])
        await s.commit()
        current, stranger = _current(agency), _current(other)
        signal_id, prop_id = signal.id, prop.id

    async with async_session() as s:
        got_signal = await get_signal(signal_id, current=current, session=s)
        assert got_signal["raw_text"] == "Куплю квартиру в Геленджике"
        assert got_signal["intent_score"] == 85

        got_prop = await get_property(prop_id, current=current, session=s)
        assert got_prop["title"] == "Студия"

        with pytest.raises(NotFoundError):
            await get_signal(signal_id, current=stranger, session=s)
        with pytest.raises(NotFoundError):
            await get_property(prop_id, current=stranger, session=s)


@pytest.mark.asyncio
async def test_signal_detail_matches_the_list_shape():
    """The detail screen renders the same fields, so the shapes must not drift."""
    from app.database import async_session, run_migrations
    from app.models.signal import Signal
    from app.routers.signals import get_signal, list_signals

    await run_migrations()
    async with async_session() as s:
        agency = await _agency(s, "Shape Agency")
        signal = Signal(agency_id=agency.id, raw_text="Ищу дом", urgency="warm")
        s.add(signal)
        await s.commit()
        current, signal_id = _current(agency), signal.id

    async with async_session() as s:
        listed = (await list_signals(current=current, session=s))["signals"][0]
        detail = await get_signal(signal_id, current=current, session=s)

    assert listed == detail
