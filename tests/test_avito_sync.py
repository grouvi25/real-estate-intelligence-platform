"""ТЗ «Avito + фильтрация сигналов» v1, блок 1: the catalogue from Avito."""
import os
import uuid
from types import SimpleNamespace

import httpx
import pytest

from app.services import avito_sync
from app.services.avito_client import PER_PAGE, AvitoClient, AvitoError

db_only = pytest.mark.skipif(os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL")


def _item(i, title="2-к. квартира, 54,3 м², 3/9 эт.", category="Квартиры", price=7_500_000,
          address="Краснодарский край, Геленджик, ул. Морская, 15", status="active"):
    return {"id": i, "title": title, "price": price, "status": status,
            "url": f"https://www.avito.ru/gelendzhik/kvartiry/x_{i}",
            "category": {"id": 24, "name": category}, "address": address}


@pytest.mark.parametrize("title,expected", [
    ("2-к. квартира, 54,3 м², 3/9 эт.", {"rooms": 2, "area_total": 54.3, "floor": 3, "floors_total": 9}),
    ("Квартира-студия, 25 м², 2/5 эт.", {"rooms": 0, "area_total": 25.0, "floor": 2, "floors_total": 5}),
    ("3-комн. квартира 80 м2", {"rooms": 3, "area_total": 80.0}),
    ("Дом 120 м² на участке 6 сот.", {"area_total": 120.0}),
    ("Участок 6 сот. (ИЖС)", {}),
])
def test_what_the_title_says(title, expected):
    assert avito_sync.parse_title(title) == expected


def test_only_values_the_schema_accepts():
    """The ТЗ mapped to room/townhouse/garage and status "archived"; the CHECK
    constraints allow none of them."""
    allowed_types = {"apartment", "house", "commercial", "land", "studio"}
    for category, title in [("Квартиры", "1-к. квартира"), ("Квартиры", "Квартира-студия"),
                            ("Дома, дачи, коттеджи", "Таунхаус 90 м²"), ("Земельные участки", "Участок"),
                            ("Коммерческая недвижимость", "Офис 40 м²")]:
        fields, why = avito_sync.map_item(_item(1, title=title, category=category, price=9_000_000))
        assert why is None and fields["property_type"] in allowed_types
    fields, _ = avito_sync.map_item(_item(2, status="blocked"))
    assert fields["status"] == "archive"


@pytest.mark.parametrize("item,reason", [
    (_item(1, price=35_000), "похоже на аренду"),
    (_item(1, category="Комнаты", title="Комната 14 м²"), "категория не для покупателей жилья"),
    (_item(1, category="Гаражи и машиноместа", title="Гараж"), "категория не для покупателей жилья"),
    ({"id": None, "title": "x"}, "нет id или заголовка"),
])
def test_what_is_not_imported(item, reason):
    assert avito_sync.map_item(item) == (None, reason)


def test_cheap_land_is_still_a_sale():
    fields, why = avito_sync.map_item(_item(1, title="Участок 4 сот.", category="Земельные участки",
                                            price=450_000))
    assert why is None and fields["property_type"] == "land"


def test_price_shape_and_price_per_sqm():
    fields, _ = avito_sync.map_item({**_item(3), "price": {"value": 5_430_000}})
    assert fields["price"] == 5_430_000 and fields["price_per_sqm"] == 100_000


def test_listing_goes_to_the_city_in_its_address():
    gel = SimpleNamespace(id="g1", city_name="Геленджик", geo_type="base")
    ana = SimpleNamespace(id="g2", city_name="Анапа", geo_type="sales")
    assert avito_sync.pick_geo([gel, ana], "Краснодарский край, Анапа, Пионерский пр.").id == "g2"
    assert avito_sync.pick_geo([ana, gel], "где-то без города").id == "g1"  # the base city
    assert avito_sync.pick_geo([], "Анапа") is None


# ------------------------------------------------------------------ client

def _transport(pages, token_status=200):
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path == "/token":
            if token_status != 200:
                return httpx.Response(token_status, json={"error_description": "bad client"})
            return httpx.Response(200, json={"access_token": "t0k", "expires_in": 86400})
        assert request.headers["Authorization"] == "Bearer t0k"
        page = int(request.url.params["page"])
        return httpx.Response(200, json=pages[page - 1] if page <= len(pages) else {"resources": []})

    return httpx.MockTransport(handler), calls


@pytest.mark.asyncio
async def test_client_pages_through_the_list(monkeypatch):
    monkeypatch.setattr("app.services.avito_client.PAUSE", 0)
    full = {"resources": [_item(i) for i in range(PER_PAGE)]}
    last = {"data": {"resources": [_item(1000)]}}  # the other shape seen in the wild
    transport, calls = _transport([full, last])
    client = AvitoClient("id", "secret", http=httpx.AsyncClient(transport=transport))
    items = [i async for i in client.iter_items()]
    assert len(items) == PER_PAGE + 1
    item_calls = [c for c in calls if c.url.path == "/core/v1/items"]
    assert [c.url.params["page"] for c in item_calls] == ["1", "2"]
    assert item_calls[0].url.params["per_page"] == str(PER_PAGE) and PER_PAGE < 100
    assert sum(1 for c in calls if c.url.path == "/token") == 1  # token reused


@pytest.mark.asyncio
async def test_client_says_why_it_cannot_start():
    transport, _ = _transport([], token_status=400)
    client = AvitoClient("id", "wrong", http=httpx.AsyncClient(transport=transport))
    with pytest.raises(AvitoError, match="bad client"):
        [i async for i in client.iter_items()]


# ---------------------------------------------------------------- database

async def _items(*items):
    for item in items:
        yield item


async def _agency(with_geo=True):
    from app.database import async_session, run_migrations
    from app.models.agency import Agency
    from app.models.geo_location import GeoLocation

    await run_migrations()
    async with async_session() as s:
        agency = Agency(name="Avito агентство", base_city="Геленджик")
        s.add(agency)
        await s.flush()
        geo_id = None
        if with_geo:
            geo = GeoLocation(agency_id=agency.id, city_name="Геленджик", geo_type="base")
            s.add(geo)
            await s.flush()
            geo_id = geo.id
        await s.commit()
        return agency.id, geo_id


@db_only
@pytest.mark.asyncio
async def test_sync_is_idempotent_and_archives_what_left_avito():
    from sqlalchemy import select

    from app.database import async_session, engine
    from app.models.property import Property

    base = int(uuid.uuid4().int % 10 ** 9)
    try:
        agency_id, geo_id = await _agency()
        async with async_session() as s:
            first = await avito_sync.sync_agency(s, agency_id, _items(_item(base + 1), _item(base + 2),
                                                                      _item(base + 3, price=30_000)))
        async with async_session() as s:
            again = await avito_sync.sync_agency(s, agency_id, _items(_item(base + 1, price=7_900_000)))
        async with async_session() as s:
            rows = {p.avito_id: p for p in (await s.execute(select(Property).where(
                Property.agency_id == agency_id))).scalars()}
        async with async_session() as s:
            silent = await avito_sync.sync_agency(s, agency_id, _items())
    finally:
        await engine.dispose()
    assert (first.created, first.skipped) == (2, 1)
    assert (again.created, again.updated, again.archived) == (0, 1, 1)
    assert rows[base + 1].price == 7_900_000 and rows[base + 1].status == "active"
    assert rows[base + 1].geo_location_id == geo_id  # matching can find it
    assert rows[base + 1].rooms == 2 and rows[base + 1].source_system == "avito"
    assert rows[base + 2].status == "archive" and rows[base + 2].avito_status == "removed"
    assert silent.archived == 0  # an empty answer must not wipe the catalogue


@db_only
@pytest.mark.asyncio
async def test_a_row_uploaded_by_hand_is_adopted_not_duplicated():
    from sqlalchemy import func, select

    from app.database import async_session, engine
    from app.models.property import Property

    item = _item(int(uuid.uuid4().int % 10 ** 9))
    try:
        agency_id, _ = await _agency()
        async with async_session() as s:
            s.add(Property(agency_id=agency_id, title="Из Excel", source_url=item["url"], status="active"))
            await s.commit()
        async with async_session() as s:
            stats = await avito_sync.sync_agency(s, agency_id, _items(item))
            count = await s.scalar(select(func.count(Property.id)).where(Property.agency_id == agency_id))
    finally:
        await engine.dispose()
    assert (stats.created, stats.updated, count) == (0, 1, 1)


@db_only
@pytest.mark.asyncio
async def test_env_keys_serve_only_the_owner_agency(monkeypatch):
    from app.config import config
    from app.database import async_session, engine
    from app.models.agency import Agency

    try:
        owner_id, _ = await _agency()
        other_id, _ = await _agency()
        monkeypatch.setattr(config, "avito_client_id", "cid")
        monkeypatch.setattr(config, "avito_client_secret", "sec")
        monkeypatch.setattr(config, "platform_owner_agency_id", str(owner_id))
        async with async_session() as s:
            owner = await avito_sync.credentials_for(s, await s.get(Agency, owner_id))
            other = await avito_sync.credentials_for(s, await s.get(Agency, other_id))
    finally:
        await engine.dispose()
    assert owner == ("cid", "sec") and other is None


@db_only
@pytest.mark.asyncio
async def test_keys_fetched_through_topnlab_are_used():
    from app.database import async_session, engine
    from app.models.agency import Agency
    from app.models.agency_crm_config import AgencyCRMConfig
    from app.services.topnlab_adapter import encrypt_blob

    try:
        agency_id, _ = await _agency()
        async with async_session() as s:
            cfg = AgencyCRMConfig(agency_id=agency_id, crm_type="topnlab", is_active=True,
                                  config={"avito_credentials_encrypted": encrypt_blob(
                                      [{"client_id": "tl-id", "client_secret": "tl-secret"}])})
            cfg.api_key = "k"
            s.add(cfg)
            await s.commit()
            creds = await avito_sync.credentials_for(s, await s.get(Agency, agency_id))
    finally:
        await engine.dispose()
    assert creds == ("tl-id", "tl-secret")
