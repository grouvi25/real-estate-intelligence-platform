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
