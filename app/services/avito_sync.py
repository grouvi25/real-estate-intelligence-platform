"""Agency catalogue from its Avito account. ТЗ «Avito + фильтрация» v1, блок 1.

Idempotent: an Avito listing is one Property per agency (agency_id, avito_id);
a row the agency uploaded earlier with the same link is adopted rather than
duplicated. Listings gone from Avito are archived, not deleted -- leads and
matches point at them.

Differences from the ТЗ, each for a reason found in the schema:

- property_type and status only take values the CHECK constraints allow
  (apartment/studio/house/land/commercial; active/archive). The ТЗ wrote room,
  townhouse, garage and "archived", and every such insert would have failed.
- The category is recognised by its name, which Avito returns with each item,
  not by the numeric ids hard-coded in the ТЗ, which could not be verified.
- Rentals are not imported: matching offers the catalogue to buyers and does not
  look at deal_type. The list API does not say sale or rent, so a home priced
  under RENT_PRICE_CEILING is taken for a rental.
- Every row is tied to one of the agency's cities: matching only searches the
  lead's city, and a row without one would never be offered to anybody.
- An empty answer while the agency has active Avito rows archives nothing: one
  failed page must not wipe the catalogue.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import select

logger = structlog.get_logger()

RENT_PRICE_CEILING = 1_000_000
SKIPPED_CATEGORIES = ("комнат", "гараж", "машиномест", "за рубежом")


@dataclass
class SyncStats:
    created: int = 0
    updated: int = 0
    archived: int = 0
    skipped: int = 0
    errors: int = 0
    reasons: dict = field(default_factory=dict)

    def skip(self, reason: str) -> None:
        self.skipped += 1
        self.reasons[reason] = self.reasons.get(reason, 0) + 1

    def as_dict(self) -> dict:
        return {"created": self.created, "updated": self.updated, "archived": self.archived,
                "skipped": self.skipped, "errors": self.errors, "skip_reasons": self.reasons}


def _number(text: str) -> Optional[float]:
    try:
        return float(text.replace(",", ".").replace(" ", "").replace(" ", ""))
    except ValueError:
        return None


def parse_title(title: str) -> dict:
    """What Avito puts in a flat's or house's title.

    «2-к. квартира, 54,3 м², 3/9 эт.» · «Квартира-студия, 25 м², 2/5 эт.» ·
    «Дом 120 м² на участке 6 сот.» · «Участок 6 сот. (ИЖС)»
    """
    t = (title or "").lower()
    out: dict[str, Any] = {}
    rooms = re.search(r"(\d+)\s*-?\s*к\b|(\d+)\s*-?\s*комн", t)
    if rooms:
        out["rooms"] = int(rooms.group(1) or rooms.group(2))
    elif "студи" in t:
        out["rooms"] = 0
    area = re.search(r"(\d+(?:[.,]\d+)?)\s*м[²2]", t)
    if area:
        out["area_total"] = _number(area.group(1))
    floors = re.search(r"(\d+)\s*/\s*(\d+)\s*эт", t)
    if floors:
        out["floor"], out["floors_total"] = int(floors.group(1)), int(floors.group(2))
    return out


def property_type_for(category_name: str, title: str) -> Optional[str]:
    c, t = (category_name or "").lower(), (title or "").lower()
    if any(word in c for word in SKIPPED_CATEGORIES):
        return None
    if "квартир" in c or "квартир" in t:
        return "studio" if "студи" in t else "apartment"
    if "дом" in c or "дач" in c or "коттедж" in c or "таунхаус" in t:
        return "house"
    if "участ" in c or "земел" in c:
        return "land"
    if "коммерч" in c:
        return "commercial"
    return None


def _price(item: dict) -> Optional[int]:
    price = item.get("price")
    if isinstance(price, dict):
        price = price.get("value")
    try:
        return int(float(price)) if price is not None else None
    except (TypeError, ValueError):
        return None


def _address(item: dict) -> Optional[str]:
    address = item.get("address")
    if isinstance(address, dict):
        address = address.get("name") or address.get("address")
    return str(address).strip() or None if address else None


def map_item(item: dict) -> tuple[Optional[dict], Optional[str]]:
    """(Property fields, None) or (None, why it is skipped)."""
    avito_id = item.get("id")
    title = str(item.get("title") or "").strip()
    if not avito_id or not title:
        return None, "нет id или заголовка"
    category = item.get("category") or {}
    ptype = property_type_for(category.get("name", "") if isinstance(category, dict) else "", title)
    if ptype is None:
        return None, "категория не для покупателей жилья"
    price = _price(item)
    if ptype in ("apartment", "studio", "house") and price is not None and price < RENT_PRICE_CEILING:
        return None, "похоже на аренду"
    fields = {
        "avito_id": int(avito_id),
        "avito_status": item.get("status"),
        "avito_synced_at": datetime.now(timezone.utc),
        "source_system": "avito",
        "source_url": item.get("url"),
        "title": title[:500],
        "property_type": ptype,
        "deal_type": "sale",
        "price": price,
        "address": _address(item),
        "status": "active" if item.get("status", "active") == "active" else "archive",
        **parse_title(title),
    }
    if fields["price"] and fields.get("area_total"):
        fields["price_per_sqm"] = int(fields["price"] / fields["area_total"])
    return fields, None


def pick_geo(geos: list, address: Optional[str]):
    """The agency city this listing belongs to."""
    from app.services.onboarding import normalize_city  # noqa: PLC0415

    addr = normalize_city(address or "")
    for geo in geos:
        if normalize_city(geo.city_name) and normalize_city(geo.city_name) in addr:
            return geo
    base = [g for g in geos if g.geo_type == "base"]
    return (base or geos or [None])[0]


async def sync_agency(session, agency_id, items) -> SyncStats:
    """Upsert ``items`` (an async iterable of Avito listings) into the catalogue."""
    from app.models.geo_location import GeoLocation  # noqa: PLC0415
    from app.models.property import Property  # noqa: PLC0415

    stats = SyncStats()
    geos = (await session.execute(select(GeoLocation).where(
        GeoLocation.agency_id == agency_id))).scalars().all()
    seen: set[int] = set()
    async for item in items:
        fields, reason = map_item(item)
        if fields is None:
            stats.skip(reason)
            continue
        seen.add(fields["avito_id"])
        try:
            # A savepoint per listing: one bad row rolls back alone.
            async with session.begin_nested():
                existing = await session.scalar(select(Property).where(
                    Property.agency_id == agency_id, Property.avito_id == fields["avito_id"]))
                if existing is None and fields.get("source_url"):
                    existing = await session.scalar(select(Property).where(
                        Property.agency_id == agency_id, Property.source_url == fields["source_url"]))
                geo = pick_geo(geos, fields.get("address"))
                if existing is None:
                    session.add(Property(agency_id=agency_id, geo_location_id=geo.id if geo else None,
                                         **fields))
                else:
                    for key, value in fields.items():
                        if value is not None:
                            setattr(existing, key, value)
                    if existing.geo_location_id is None and geo is not None:
                        existing.geo_location_id = geo.id
            if existing is None:
                stats.created += 1
            else:
                stats.updated += 1
        except Exception as e:  # noqa: BLE001 - one bad listing must not stop the rest
            stats.errors += 1
            logger.warning("Avito listing not saved", avito_id=fields.get("avito_id"), error=str(e)[:200])

    active_avito = (await session.execute(select(Property).where(
        Property.agency_id == agency_id, Property.source_system == "avito",
        Property.status == "active"))).scalars().all()
    if not seen and active_avito:
        logger.warning("Avito returned nothing; catalogue left as it is",
                       agency_id=str(agency_id), active=len(active_avito))
    else:
        for prop in active_avito:
            if prop.avito_id not in seen:
                prop.status = "archive"
                prop.avito_status = "removed"
                stats.archived += 1
    await session.commit()
    logger.info("Avito sync", agency_id=str(agency_id), **stats.as_dict())
    return stats


# ------------------------------------------------------------ whose account

async def credentials_for(session, agency) -> Optional[tuple[str, str]]:
    """Which Avito account belongs to the agency.

    1. Keys the agency pulled from TopNLab (Профиль → TopNLab → «Получить ключи
       Avito»), if they carry client_id and client_secret.
    2. AVITO_CLIENT_ID / AVITO_CLIENT_SECRET from .env -- the ТЗ's single-agency
       setup -- for the platform owner's agency only, so a second client never
       gets the first client's listings.
    """
    from app.config import config  # noqa: PLC0415
    from app.services.topnlab_adapter import decrypt_blob, load_config  # noqa: PLC0415

    cfg = await load_config(session, agency.id)
    blob = decrypt_blob((cfg.config or {}).get("avito_credentials_encrypted")) if cfg else None
    candidates = blob if isinstance(blob, list) else [blob]
    for entry in candidates:
        if isinstance(entry, dict):
            cid = entry.get("client_id") or entry.get("clientId")
            secret = entry.get("client_secret") or entry.get("clientSecret")
            if cid and secret:
                return str(cid), str(secret)
    if config.avito_client_id and config.avito_client_secret:
        owner = config.platform_owner_agency_id
        if owner and str(agency.id) == str(owner):
            return config.avito_client_id, config.avito_client_secret
    return None


async def sync_all(client_factory=None) -> dict:
    """Sync every active agency that has an Avito account. Returns per-agency stats."""
    from app.database import async_session  # noqa: PLC0415
    from app.models.agency import Agency  # noqa: PLC0415
    from app.services.avito_client import AvitoClient, AvitoError  # noqa: PLC0415
    from app.services.billing import collectable_agencies_clause  # noqa: PLC0415

    factory = client_factory or (lambda cid, secret: AvitoClient(cid, secret))
    results: dict[str, Any] = {}
    async with async_session() as session:
        agencies = (await session.execute(select(Agency).where(
            collectable_agencies_clause()))).scalars().all()
        for agency in agencies:
            creds = await credentials_for(session, agency)
            if creds is None:
                continue
            client = factory(*creds)
            try:
                stats = await sync_agency(session, agency.id, client.iter_items("active"))
                results[str(agency.id)] = stats.as_dict()
            except AvitoError as e:
                await session.rollback()
                results[str(agency.id)] = {"error": str(e)}
                logger.warning("Avito sync failed", agency_id=str(agency.id), error=str(e))
            finally:
                await client.close()
    return results
