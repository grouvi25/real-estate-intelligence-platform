"""Find the RSS/Atom feed of a site: <link rel="alternate">, then the usual paths."""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urljoin, urlsplit

from app.services.discovery.clients import robots_allows

_ALTERNATE = re.compile(
    r"<link[^>]+type=[\"']application/(?:rss|atom)\+xml[\"'][^>]*>", re.IGNORECASE)
_HREF = re.compile(r"href=[\"']([^\"']+)[\"']", re.IGNORECASE)
COMMON_PATHS = ("/rss", "/feed", "/rss.xml", "/feed.xml", "/news/rss", "/index.rss")


def _looks_like_feed(text: str) -> bool:
    head = text[:600].lower()
    return "<rss" in head or "<feed" in head or "<rdf" in head


async def discover_feed(http, site: str) -> Optional[str]:
    """Feed URL of ``site`` (a domain or URL), or None. Honours robots.txt."""
    if "://" not in site:
        site = "https://" + site.strip("/")
    parts = urlsplit(site)
    home = f"{parts.scheme}://{parts.netloc}/"
    if not await robots_allows(http, home):
        return None
    try:
        res = await http.get(home)
    except Exception:  # noqa: BLE001
        return None
    if res.status_code < 400:
        for tag in _ALTERNATE.findall(res.text[:200_000]):
            href = _HREF.search(tag)
            if href:
                return urljoin(str(res.url), href.group(1))
    for path in COMMON_PATHS:
        url = urljoin(home, path)
        if not await robots_allows(http, url):
            continue
        try:
            probe = await http.get(url)
        except Exception:  # noqa: BLE001
            continue
        if probe.status_code < 400 and _looks_like_feed(probe.text):
            return str(probe.url)
    return None
