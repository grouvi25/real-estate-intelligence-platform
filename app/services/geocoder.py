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


# Search is biased towards where the agency works, and it took measuring to find
# out how. Yandex matches a prefix only inside a bounding box, and only when the
# country is named:
#
#   «Гелен»                        -> a town in the Netherlands
#   «Гелен» + box                  -> nothing
#   «Россия, Гелен» + box          -> Геленджик
#   «Россия, Краснод» + box        -> посёлок Краснодарский   (the city loses)
#   «Краснод» + box                -> Краснодар
#
# So neither spelling wins on its own: both are asked, the answers are merged,
# and what the manager typed decides the order.
_BOX_DEGREES = 2.0
_centres: dict[str, tuple[float, float, str]] = {}


async def _centre_of(city: str) -> Optional[tuple[float, float, str]]:
    """Where to bias the search, and which country to name. Looked up once."""
    if city in _centres:
        return _centres[city]
    rows = await _localities(city, None, 1)
    if not rows:
        return None
    row = rows[0]
    found = (row["lat"], row["lon"], row["country"] or "")
    _centres[city] = found
    return found


def _rank(rows: list[dict], query: str) -> list[dict]:
    """A town whose name starts with what was typed comes first.

    Without this «Краснод» answers «посёлок Краснодарский» before Краснодар:
    both match, and the geocoder has no idea which one a person meant.
    """
    q = query.strip().lower()

    def key(row: dict) -> tuple:
        name = row["name"].lower()
        return (0 if name.startswith(q) else 1, len(name), name)

    return sorted(rows, key=key)


async def suggest_cities(query: str, near: Optional[str] = None,
                         limit: int = 6) -> list[dict]:
    """Towns matching what has been typed so far."""
    query = (query or "").strip()
    if not is_available() or len(query) < 2:
        return []

    box = None
    country = ""
    if near:
        centre = await _centre_of(near)
        if centre:
            lat, lon, country = centre
            box = (f"{lon - _BOX_DEGREES},{lat - _BOX_DEGREES}~"
                   f"{lon + _BOX_DEGREES},{lat + _BOX_DEGREES}")

    attempts: list[tuple[str, Optional[str]]] = []
    if box:
        if country:
            attempts.append((f"{country}, {query}", box))
        attempts.append((query, box))

    found: list[dict] = []
    seen: set[str] = set()
    for text, bbox in attempts:
        for row in await _localities(text, bbox, limit):
            if row["name"] not in seen:
                seen.add(row["name"])
                found.append(row)

    # Nothing nearby: somebody is adding a partner on the other side of the
    # country, and there the name has to be typed out in full.
    if not found:
        found = await _localities(query, None, limit)

    return _rank(found, query)[:limit]


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
