"""Generic outbound CRM export via webhook. TZ section 32.

An agency can enable CRM export and configure a webhook URL + a field mapping
(``crm_field_mapping``: {crm_key: reip_field}). Qualified leads are pushed as a
JSON payload. This is the vendor-neutral path; vendor-specific adapters
(amoCRM/Bitrix24/etc.) live under app/services/crm/ per the Signal Bus addendum.

PII (name/phone/email) is only sent to the agency's *own* configured CRM, never
to a third party, and only for leads that have given 152-FZ consent.
"""
from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger()

# Default REIP lead -> CRM payload mapping when the agency provides none.
DEFAULT_FIELD_MAPPING: dict[str, str] = {
    "name": "name",
    "phone": "phone",
    "email": "email",
    "budget_min": "budget_min",
    "budget_max": "budget_max",
    "segment": "segment",
    "purchase_goal": "purchase_goal",
    "status": "status",
    "intent_score": "intent_score",
    "source": "source_type",
    "utm_source": "utm_source",
    "utm_campaign": "utm_campaign",
}


def _lead_field_values(lead: Any) -> dict[str, Any]:
    """Whitelisted, resolvable lead fields (PII included, decrypted on access)."""
    return {
        "name": lead.name,
        "phone": lead.phone,
        "email": lead.email,
        "telegram_username": lead.telegram_username,
        "budget_min": lead.budget_min,
        "budget_max": lead.budget_max,
        "segment": lead.segment,
        "purchase_goal": lead.purchase_goal,
        "status": lead.status,
        "intent_score": lead.intent_score,
        "source_type": lead.source_type,
        "source_platform": lead.source_platform,
        "utm_source": lead.utm_source,
        "utm_medium": lead.utm_medium,
        "utm_campaign": lead.utm_campaign,
        "lead_id": str(lead.id),
    }


def build_crm_payload(lead: Any, field_mapping: dict | None) -> dict[str, Any]:
    """Map REIP lead fields to the CRM's expected keys."""
    mapping = field_mapping or DEFAULT_FIELD_MAPPING
    values = _lead_field_values(lead)
    payload: dict[str, Any] = {}
    for crm_key, reip_field in mapping.items():
        payload[crm_key] = values.get(reip_field)
    return payload


async def export_lead_to_crm(session, lead: Any) -> dict:
    """Push a lead to the agency's configured CRM webhook.

    Returns a small status dict. Never raises on transport errors — export is a
    best-effort side channel and must not break the qualification flow.
    """
    from app.models.agency import Agency

    agency = await session.get(Agency, lead.agency_id)
    if agency is None or not agency.crm_export_enabled or not agency.crm_webhook_url:
        return {"exported": False, "reason": "disabled"}
    if not lead.consent_given:
        return {"exported": False, "reason": "no_consent"}

    payload = build_crm_payload(lead, agency.crm_field_mapping)
    payload["crm_type"] = agency.crm_type

    try:
        import httpx

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(agency.crm_webhook_url, json=payload)
        ok = resp.status_code < 400
        logger.info("CRM export", lead_id=str(lead.id), status=resp.status_code, ok=ok)
        return {"exported": ok, "status_code": resp.status_code}
    except Exception as e:  # noqa: BLE001
        logger.warning("CRM export failed", lead_id=str(lead.id), error=str(e))
        return {"exported": False, "reason": "transport_error", "error": str(e)}
