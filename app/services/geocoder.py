"""Address -> coordinates, via the Yandex HTTP Geocoder. TZ 2.3.

Why this runs on the server rather than in the browser:

* the geocoder key is billed per request. In the page it is visible to anyone
  who opens the developer console, and somebody else's traffic spends the
  agency's quota;
* Yandex restricts a key by Referer or by IP. A Mini App lives inside Telegram's
  webview, which the Yandex documentation itself warns may send no Referer at
  all -- the server has one fixed address and an IP restriction that always holds;
* the answer never changes. Found once and written to the property, it costs one
  request for the lifetime of that flat instead of one per card opened.

Credential-gated like every other integration: without a key this returns None
and the card simply shows no map.
"""
from __future__ import annotations

from typing import Optional

import structlog

from app.config import config

logger = structlog.get_logger()

GEOCODER_URL = "https://geocode-maps.yandex.ru/1.x/"
REQUEST_TIMEOUT = 15.0


def is_available() -> bool:
    return bool(config.yandex_geocoder_api_key)


async def geocode(address: str) -> Optional[tuple[float, float]]:
    """(lat, lon) for an address, or None.

    None covers three different things on purpose -- no key, no answer, and a
    service that did not respond -- because the caller does the same in all
    three: leaves the card without a map. What separates them is the log.
    """
    if not is_available() or not address or not address.strip():
        return None

    import httpx  # noqa: PLC0415

    params = {
        "apikey": config.yandex_geocoder_api_key,
        "geocode": address.strip(),
        "format": "json",
        "results": 1,
        "lang": "ru_RU",
    }
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            res = await client.get(GEOCODER_URL, params=params)
        if res.status_code == 403:
            logger.warning("Геокодер отказал — проверьте ключ и его ограничения",
                           status=res.status_code, body=res.text[:200])
            return None
        res.raise_for_status()
        found = (res.json()["response"]["GeoObjectCollection"]["featureMember"])
    except Exception as e:  # noqa: BLE001 - network, JSON shape, anything
        logger.warning("Геокодер недоступен", error=str(e), address=address[:80])
        return None

    if not found:
        logger.info("Адрес не найден геокодером", address=address[:80])
        return None

    # Yandex answers "долгота широта" -- longitude first, which is the opposite
    # of every map library's order. Swapping it here once beats swapping it at
    # every call site and getting it wrong somewhere.
    try:
        lon, lat = (float(v) for v in found[0]["GeoObject"]["Point"]["pos"].split())
    except (KeyError, ValueError):
        logger.warning("Геокодер вернул точку в неожиданном виде", address=address[:80])
        return None
    return lat, lon


# Search is biased towards where the agency works. Yandex matches a prefix only
# inside a narrow window: with a box around the Black Sea coast "Гелен" finds
# Геленджик, while a box covering all of Russia finds nothing at all. Outside the
# box the query has to be nearly complete, which is fine — a partner in Kazan is
# typed in full.
_BOX_DEGREES = 3.0
_centres: dict[str, tuple[float, float]] = {}


async def _centre_of(city: str) -> Optional[tuple[float, float]]:
    """Where to bias the search. Looked up once per city per process."""
    if city in _centres:
        return _centres[city]
    at = await geocode(city)
    if at:
        _centres[city] = at
    return at


async def suggest_cities(query: str, near: Optional[str] = None,
                         limit: int = 6) -> list[dict]:
    """Towns matching what has been typed so far.

    Two passes: close to home first, then the whole map. A manager adding a
    neighbouring town types three letters; one adding a partner on the other side
    of the country types the name out, and the second pass catches that.
    """
    query = (query or "").strip()
    if not is_available() or len(query) < 2:
        return []

    boxes: list[Optional[str]] = []
    if near:
        centre = await _centre_of(near)
        if centre:
            lat, lon = centre
            boxes.append(f"{lon - _BOX_DEGREES},{lat - _BOX_DEGREES}~"
                         f"{lon + _BOX_DEGREES},{lat + _BOX_DEGREES}")
    boxes.append(None)

    seen: set[str] = set()
    found: list[dict] = []
    for box in boxes:
        for row in await _localities(query, box, limit):
            if row["name"] in seen:
                continue
            seen.add(row["name"])
            found.append(row)
        if found:
            break
    return found[:limit]


async def _localities(query: str, bbox: Optional[str], limit: int) -> list[dict]:
    import httpx  # noqa: PLC0415

    params = {
        "apikey": config.yandex_geocoder_api_key,
        "geocode": query,
        "format": "json",
        "results": limit * 2,
        "kind": "locality",
        "lang": "ru_RU",
    }
    if bbox:
        params["bbox"] = bbox
        params["rspn"] = 1
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            res = await client.get(GEOCODER_URL, params=params)
        res.raise_for_status()
        members = res.json()["response"]["GeoObjectCollection"]["featureMember"]
    except Exception as e:  # noqa: BLE001
        logger.warning("Поиск города не удался", error=str(e), query=query[:60])
        return []

    rows = []
    for member in members:
        obj = member["GeoObject"]
        meta = obj["metaDataProperty"]["GeocoderMetaData"]
        # A query for a town also returns its airport, its railway station and
        # its cable car. Only the town itself is a town.
        if meta.get("kind") != "locality":
            continue
        parts = {c["kind"]: c["name"] for c in meta["Address"].get("Components", [])}
        name = parts.get("locality")
        if not name:
            continue
        try:
            lon, lat = (float(v) for v in obj["Point"]["pos"].split())
        except (KeyError, ValueError):
            continue
        rows.append({
            "name": name,
            "region": parts.get("province") or parts.get("area") or "",
            "country": parts.get("country") or "",
            "lat": lat,
            "lon": lon,
        })
    return rows
