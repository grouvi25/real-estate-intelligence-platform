"""Avito API: the agency's own listings. ТЗ «Avito + фильтрация» v1, блок 1.6.

OAuth2 client_credentials; the token lives 24 h and is kept in memory for the
process -- an hourly sync can afford to ask again, so the ТЗ's avito_tokens
table is not needed.

The ТЗ read items from /core/v1/accounts/{user_id}/items/. That path is the
single-item card; the list of the account's items is GET /core/v1/items
(per_page < 100, page from 1, status filter). The list carries id, title, price,
url, status, category and address -- not the description or parameters, which
is why avito_sync reads rooms, area and floors out of the title, where Avito
itself puts them («2-к. квартира, 54 м², 3/9 эт.»).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator, Optional

import httpx
import structlog

logger = structlog.get_logger()

API = "https://api.avito.ru"
PER_PAGE = 99  # the API wants strictly less than 100
MAX_PAGES = 200  # 19 800 listings: far beyond an agency, stops a runaway loop
PAUSE = 0.35  # stay under the documented request rate


class AvitoError(Exception):
    pass


class AvitoClient:
    def __init__(self, client_id: str, client_secret: str, http: Optional[httpx.AsyncClient] = None):
        self.client_id = client_id
        self.client_secret = client_secret
        self._http = http
        self._token: Optional[str] = None
        self._expires: Optional[datetime] = None

    async def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=30.0)
        return self._http

    async def close(self) -> None:
        if self._http is not None:
            await self._http.aclose()

    async def token(self) -> str:
        now = datetime.now(timezone.utc)
        if self._token and self._expires and now < self._expires - timedelta(minutes=5):
            return self._token
        http = await self._client()
        try:
            resp = await http.post(f"{API}/token", data={
                "grant_type": "client_credentials",
                "client_id": self.client_id, "client_secret": self.client_secret,
            })
        except httpx.HTTPError as e:
            raise AvitoError(f"Avito не отвечает: {type(e).__name__}") from None
        body = resp.json() if resp.content else {}
        if resp.status_code != 200 or not body.get("access_token"):
            raise AvitoError(f"Avito не выдал токен: {body.get('error_description') or resp.status_code}")
        self._token = body["access_token"]
        self._expires = now + timedelta(seconds=int(body.get("expires_in") or 86400))
        return self._token

    async def iter_items(self, status: str = "active") -> AsyncIterator[dict]:
        """Every listing of the account with that status, page by page."""
        http = await self._client()
        for page in range(1, MAX_PAGES + 1):
            headers = {"Authorization": f"Bearer {await self.token()}"}
            try:
                resp = await http.get(f"{API}/core/v1/items", headers=headers,
                                      params={"per_page": PER_PAGE, "page": page, "status": status})
            except httpx.HTTPError as e:
                raise AvitoError(f"Avito не отвечает: {type(e).__name__}") from None
            if resp.status_code != 200:
                raise AvitoError(f"Avito вернул {resp.status_code} на странице {page}")
            body = resp.json()
            items = (body.get("resources") if isinstance(body, dict) else None)
            if items is None and isinstance(body, dict):
                items = (body.get("data") or {}).get("resources")
            items = [i for i in (items or []) if isinstance(i, dict)]
            for item in items:
                yield item
            if len(items) < PER_PAGE:
                return
            await asyncio.sleep(PAUSE)
