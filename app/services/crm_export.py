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


async def _active_config(session, agency_id):
    """The agency's chosen CRM connector, if it configured one."""
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.agency_crm_config import AgencyCRMConfig  # noqa: PLC0415

    return (await session.execute(
        select(AgencyCRMConfig).where(
            AgencyCRMConfig.agency_id == agency_id,
            AgencyCRMConfig.is_active.is_(True),
        ).limit(1)
    )).scalars().first()


async def export_lead_to_crm(session, lead: Any) -> dict:
    """Push a lead to the agency's CRM.

    Which CRM is decided by agency_crm_config (Signal Bus addendum §4): a vendor
    connector when the agency configured one, the generic webhook otherwise —
    with behaviour identical to what it always was, as the addendum requires.

    Until this read the config table, the four vendor adapters were dead code:
    an agency on Topnlab got a generic webhook and nothing else.

    Returns a small status dict. Never raises on transport errors — export is a
    best-effort side channel and must not break the qualification flow.
    """
    from app.models.agency import Agency  # noqa: PLC0415
    from app.services.crm import adapter_from_config  # noqa: PLC0415

    if not lead.consent_given:
        return {"exported": False, "reason": "no_consent"}

    cfg = await _active_config(session, lead.agency_id)
    if cfg is not None:
        adapter = adapter_from_config(cfg)
        if adapter is not None:
            values = _lead_field_values(lead)
            result = await adapter.export(values)
            deal_id = result.get("crm_deal_id")
            if deal_id and not lead.crm_deal_id:
                # The one link that lets revenue be traced back to the signal.
                lead.crm_deal_id = deal_id
                await session.commit()
            logger.info("CRM export via connector", lead_id=str(lead.id),
                        crm=cfg.crm_type, ok=result.get("exported"))
            return result
        logger.warning("CRM config has an unknown connector; falling back to webhook",
                       lead_id=str(lead.id), crm_type=cfg.crm_type)

    agency = await session.get(Agency, lead.agency_id)
    if agency is None or not agency.crm_export_enabled or not agency.crm_webhook_url:
        return {"exported": False, "reason": "disabled"}

    payload = build_crm_payload(lead, agency.crm_field_mapping)
    payload["crm_type"] = agency.crm_type

    try:
        import httpx  # noqa: PLC0415

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(agency.crm_webhook_url, json=payload)
        ok = resp.status_code < 400
        logger.info("CRM export", lead_id=str(lead.id), status=resp.status_code, ok=ok)
        return {"exported": ok, "status_code": resp.status_code}
    except Exception as e:  # noqa: BLE001
        logger.warning("CRM export failed", lead_id=str(lead.id), error=str(e))
        return {"exported": False, "reason": "transport_error", "error": str(e)}


async def push_outcome_to_crm(session, lead: Any, outcome: Any) -> dict:
    """Report a closed deal to the agency's CRM connector.

    The addendum's CRMConnector has two halves; only the first was ever called,
    so a deal closed in REIP never reached the CRM it came from.
    """
    from app.services.crm import adapter_from_config  # noqa: PLC0415

    if not lead.consent_given:
        return {"exported": False, "reason": "no_consent"}

    cfg = await _active_config(session, lead.agency_id)
    if cfg is None:
        return {"exported": False, "reason": "no_connector"}
    adapter = adapter_from_config(cfg)
    if adapter is None:
        return {"exported": False, "reason": "unknown_connector", "crm_type": cfg.crm_type}

    values = _lead_field_values(lead)
    values["crm_deal_id"] = lead.crm_deal_id
    result = await adapter.push_outcome(values, outcome)
    logger.info("CRM outcome pushed", lead_id=str(lead.id), crm=cfg.crm_type,
                ok=result.get("exported"))
    return result
