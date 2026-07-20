"""CRM adapter base. Signal Bus addendum.

A CRMAdapter turns a normalized lead-values dict (see crm_export._lead_field_values)
into a vendor-specific payload and POSTs it. build_payload is pure (unit-testable);
export performs the HTTP call and never raises (best-effort side channel).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

import structlog

logger = structlog.get_logger()


class CRMAdapter(ABC):
    crm_type: str = "generic"

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        config: Optional[dict] = None,
        field_mapping: Optional[dict] = None,
    ):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key
        self.config = config or {}
        self.field_mapping = field_mapping or {}

    @abstractmethod
    def endpoint(self) -> str:
        """Absolute URL to POST the lead to."""

    @abstractmethod
    def build_payload(self, lead_values: dict) -> dict:
        """Vendor-specific request body for one lead."""

    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    async def export(self, lead_values: dict) -> dict:
        """POST the lead; return a small status dict (never raises)."""
        url = self.endpoint()
        if not url:
            return {"exported": False, "reason": "not_configured", "crm": self.crm_type}
        try:
            import httpx

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=self.build_payload(lead_values),
                                         headers=self.headers())
            ok = resp.status_code < 400
            logger.info("CRM adapter export", crm=self.crm_type, status=resp.status_code, ok=ok)
            return {"exported": ok, "status_code": resp.status_code, "crm": self.crm_type}
        except Exception as e:  # noqa: BLE001
            logger.warning("CRM adapter export failed", crm=self.crm_type, error=str(e))
            return {"exported": False, "reason": "transport_error", "crm": self.crm_type}


def _mapped(lead_values: dict, field_mapping: dict, default_key: str, source_field: str) -> Any:
    """Value for a CRM key, honoring an agency override in field_mapping."""
    source = field_mapping.get(default_key, source_field)
    return lead_values.get(source)
