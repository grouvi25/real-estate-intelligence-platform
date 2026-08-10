"""Geocoding: one billed request per property, ever.

The catalogue keeps a postal address and no coordinates. Yandex charges per
lookup, so the danger is not that it fails — it is that it succeeds, quietly,
several hundred times a day on the same twenty flats.
"""
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL"
)


class _Counter:
    """Stands in for the geocoder and counts how often it is asked."""

    def __init__(self, answer=(44.5622, 38.0771)):
        self.answer = answer
        self.calls = []

    def is_available(self):
        return True

    async def geocode(self, address):
        self.calls.append(address)
        return self.answer


async def _property(session, address="ул. Мира, 15"):
    from app.models.agency import Agency
    from app.models.geo_location import GeoLocation
    from app.models.property import Property

    agency = Agency(name="Geo Agency", base_city="Геленджик")
    session.add(agency)
    await session.flush()
    geo = GeoLocation(agency_id=agency.id, city_name="Геленджик", geo_type="base")
    session.add(geo)
    await session.flush()
    prop = Property(agency_id=agency.id, geo_location_id=geo.id, title="2к у моря",
                    price=7_900_000, status="active", address=address, district="Тонкий мыс")
    session.add(prop)
    await session.commit()
    return agency, prop


@pytest.mark.asyncio
async def test_an_address_is_looked_up_once_and_kept(monkeypatch):
    from app.database import async_session, run_migrations
    from app.dependencies import CurrentManager
    from app.routers import properties as router

    await run_migrations()
    async with async_session() as s:
        agency, prop = await _property(s)
        agency_id, prop_id = str(agency.id), prop.id

    fake = _Counter()
    monkeypatch.setattr("app.services.geocoder.is_available", fake.is_available)
    monkeypatch.setattr("app.services.geocoder.geocode", fake.geocode)
    current = CurrentManager(manager_id="m1", agency_id=agency_id)

    async with async_session() as s:
        first = await router.get_property(prop_id, current=current, session=s)
    assert first["lat"] == pytest.approx(44.5622)
    assert first["lon"] == pytest.approx(38.0771)

    # Второе открытие карточки не должно стоить ещё одного запроса.
    async with async_session() as s:
        second = await router.get_property(prop_id, current=current, session=s)
    assert second["lat"] == pytest.approx(44.5622)
    assert len(fake.calls) == 1, f"геокодер вызван {len(fake.calls)} раз(а) вместо одного"

    # Город обязан попасть в запрос: «Тонкий мыс» без города — не адрес.
    assert "Геленджик" in fake.calls[0]
    # А район — не должен: с ним Яндекс отвечает центром микрорайона вместо дома,
    # и метка уезжает на пару километров.
    assert "Тонкий мыс" not in fake.calls[0], f"район портит запрос: {fake.calls[0]}"
    assert "ул. Мира, 15" in fake.calls[0]


@pytest.mark.asyncio
async def test_without_a_street_the_district_is_better_than_nothing(monkeypatch):
    """Not every catalogue row has a house number; the neighbourhood still puts
    the pin in the right town."""
    from app.database import async_session, run_migrations
    from app.dependencies import CurrentManager
    from app.routers import properties as router

    await run_migrations()
    async with async_session() as s:
        agency, prop = await _property(s, address=None)
        agency_id, prop_id = str(agency.id), prop.id

    fake = _Counter()
    monkeypatch.setattr("app.services.geocoder.is_available", fake.is_available)
    monkeypatch.setattr("app.services.geocoder.geocode", fake.geocode)

    async with async_session() as s:
        await router.get_property(prop_id,
                                  current=CurrentManager(manager_id="m1", agency_id=agency_id),
                                  session=s)
    assert fake.calls == ["Геленджик, Тонкий мыс"]


@pytest.mark.asyncio
async def test_an_address_that_cannot_be_found_is_not_retried_for_ever(monkeypatch):
    """A stamp is left even on failure, or every open pays for the same miss."""
    from app.database import async_session, run_migrations
    from app.dependencies import CurrentManager
    from app.routers import properties as router

    await run_migrations()
    async with async_session() as s:
        agency, prop = await _property(s, address="где-то там")
        agency_id, prop_id = str(agency.id), prop.id

    fake = _Counter(answer=None)
    monkeypatch.setattr("app.services.geocoder.is_available", fake.is_available)
    monkeypatch.setattr("app.services.geocoder.geocode", fake.geocode)
    current = CurrentManager(manager_id="m1", agency_id=agency_id)

    for _ in range(3):
        async with async_session() as s:
            card = await router.get_property(prop_id, current=current, session=s)
    assert card["lat"] is None
    assert len(fake.calls) == 1, f"неудачный адрес переспрашивался {len(fake.calls)} раз(а)"


@pytest.mark.asyncio
async def test_without_a_key_nothing_is_asked_and_the_card_still_works(monkeypatch):
    from app.database import async_session, run_migrations
    from app.dependencies import CurrentManager
    from app.routers import properties as router

    await run_migrations()
    async with async_session() as s:
        agency, prop = await _property(s)
        agency_id, prop_id = str(agency.id), prop.id

    called = []
    monkeypatch.setattr("app.services.geocoder.is_available", lambda: False)
    monkeypatch.setattr("app.services.geocoder.geocode",
                        lambda a: called.append(a))
    current = CurrentManager(manager_id="m1", agency_id=agency_id)

    async with async_session() as s:
        card = await router.get_property(prop_id, current=current, session=s)
    assert card["lat"] is None and card["lon"] is None
    assert card["address"] == "ул. Мира, 15", "карточка должна работать и без карты"
    assert called == []


def test_the_geocoder_key_never_reaches_the_browser():
    """It is billed per request. In the page anyone can spend the agency's quota."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    auth = (root / "app" / "routers" / "auth.py").read_text(encoding="utf-8")
    assert "yandex_geocoder_api_key" not in auth, \
        "ключ геокодера уехал в ответ авторизации"

    # Ищем вызов, а не слово: в шапке файла geocode упоминается объяснением,
    # почему его здесь нет.
    maps_js = (root / "mini_app" / "js" / "maps.js").read_text(encoding="utf-8")
    code = [line for line in maps_js.splitlines()
            if not line.strip().startswith(("//", "*", "/*"))]
    assert ".geocode(" not in chr(10).join(code), "фронт снова геокодирует сам"
