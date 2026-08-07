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

    # Vendors name the created record differently; these are the keys they
    # actually answer with, in the order we trust them.
    ID_KEYS = ("crm_deal_id", "deal_id", "lead_id", "id", "result")

    def extract_deal_id(self, body: Any) -> Optional[str]:
        """The vendor's id for the record just created, if it gave one.

        Without this the chain signal -> lead -> CRM deal cannot be closed:
        lead.crm_deal_id stays empty and no revenue can be attributed back.
        """
        if isinstance(body, (str, int)):
            return str(body) or None
        if not isinstance(body, dict):
            return None
        for key in self.ID_KEYS:
            value = body.get(key)
            if isinstance(value, (str, int)) and str(value):
                return str(value)
            # amoCRM answers {"_embedded": {"leads": [{"id": 123}]}}
            if isinstance(value, dict):
                nested = self.extract_deal_id(value)
                if nested:
                    return nested
        embedded = body.get("_embedded") or {}
        for items in embedded.values() if isinstance(embedded, dict) else []:
            if isinstance(items, list) and items:
                nested = self.extract_deal_id(items[0])
                if nested:
                    return nested
        return None

    def outcome_endpoint(self) -> str:
        """Where a closed deal is reported. Defaults to the lead endpoint."""
        return self.endpoint()

    def build_outcome_payload(self, lead_values: dict, outcome: Any) -> dict:
        """Vendor body for a recorded outcome. Overridable per vendor."""
        return {
            "external_id": lead_values.get("lead_id"),
            "crm_deal_id": lead_values.get("crm_deal_id"),
            "outcome": getattr(outcome, "outcome", None),
            "deal_amount": getattr(outcome, "deal_amount", None),
            "commission_amount": getattr(outcome, "commission_amount", None),
            "closed_at": (getattr(outcome, "deal_closed_at", None).isoformat()
                          if getattr(outcome, "deal_closed_at", None) else None),
        }

    async def _post(self, url: str, payload: dict, what: str) -> dict:
        if not url:
            return {"exported": False, "reason": "not_configured", "crm": self.crm_type}
        try:
            import httpx  # noqa: PLC0415

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=payload, headers=self.headers())
            ok = resp.status_code < 400
            body = None
            try:
                body = resp.json()
            except Exception:  # noqa: BLE001 - not every CRM answers JSON
                body = None
            logger.info("CRM adapter " + what, crm=self.crm_type,
                        status=resp.status_code, ok=ok)
            result = {"exported": ok, "status_code": resp.status_code, "crm": self.crm_type}
            deal_id = self.extract_deal_id(body) if ok else None
            if deal_id:
                result["crm_deal_id"] = deal_id
            return result
        except Exception as e:  # noqa: BLE001
            logger.warning("CRM adapter " + what + " failed", crm=self.crm_type, error=str(e))
            return {"exported": False, "reason": "transport_error", "crm": self.crm_type}

    async def export(self, lead_values: dict) -> dict:
        """POST the lead; return a small status dict (never raises)."""
        return await self._post(self.endpoint(), self.build_payload(lead_values), "export")

    async def push_outcome(self, lead_values: dict, outcome: Any) -> dict:
        """Report a closed deal back to the CRM (never raises)."""
        return await self._post(self.outcome_endpoint(),
                                self.build_outcome_payload(lead_values, outcome), "outcome")


def _mapped(lead_values: dict, field_mapping: dict, default_key: str, source_field: str) -> Any:
    """Value for a CRM key, honoring an agency override in field_mapping."""
    source = field_mapping.get(default_key, source_field)
    return lead_values.get(source)
