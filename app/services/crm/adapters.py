"""Vendor CRM adapters: Topnlab, amoCRM, Bitrix24, YUcrm. Signal Bus addendum.

Each adapter targets its vendor's documented lead-create endpoint and payload
shape. Credentials/base URL come from agency_crm_config. build_payload is pure.
"""
from __future__ import annotations

from app.services.crm.base import CRMAdapter


class TopnlabAdapter(CRMAdapter):
    """Shape of a TopNLab buyer order (API колл-центра, раздел 2).

    The export itself does not go through here: crm_export hands TopNLab leads
    to app.services.topnlab_adapter, which also sets the call task and keeps the
    order id on the lead. This class stays so the registry, the settings screen
    and anything reading the payload shape see the real endpoint -- it used to
    point at an invented /api/leads.
    """

    crm_type = "topnlab"

    def endpoint(self) -> str:
        from app.config import config  # noqa: PLC0415

        return f"{self.base_url or config.topnlab_base_url.rstrip('/')}/call/main/importClient/"

    def headers(self) -> dict:
        return {}  # the key travels in the body as appkey

    def build_payload(self, lead_values: dict) -> dict:
        phone = "".join(ch for ch in str(lead_values.get("phone") or "") if ch.isdigit())
        return {
            "appkey": self.api_key,
            "fullname": lead_values.get("name") or "Покупатель из REIP",
            "phone": phone,
            "action": 1,
            "object_type": "flat",
            "comment": f"[REIP] Score: {lead_values.get('intent_score') or 0}/100 | "
                       f"lead {lead_values.get('lead_id')}"[:500],
        }


class AmoCrmAdapter(CRMAdapter):
    crm_type = "amocrm"

    def endpoint(self) -> str:
        return f"{self.base_url}/api/v4/leads/complex" if self.base_url else ""

    def build_payload(self, lead_values: dict) -> dict:
        # amoCRM /leads/complex expects a list of lead objects with an embedded
        # contact carrying the phone in custom_fields_values.
        return [
            {
                "name": lead_values.get("name") or "Лид REIP",
                "price": lead_values.get("budget_max") or 0,
                "_embedded": {
                    "contacts": [
                        {
                            "name": lead_values.get("name"),
                            "custom_fields_values": [
                                {"field_code": "PHONE",
                                 "values": [{"value": lead_values.get("phone")}]},
                            ],
                        }
                    ]
                },
            }
        ]


class Bitrix24Adapter(CRMAdapter):
    crm_type = "bitrix24"

    def endpoint(self) -> str:
        # base_url is the inbound webhook base, e.g. https://x.bitrix24.ru/rest/1/<token>
        return f"{self.base_url}/crm.lead.add.json" if self.base_url else ""

    def headers(self) -> dict:
        return {}  # auth is embedded in the webhook URL

    def build_payload(self, lead_values: dict) -> dict:
        return {
            "fields": {
                "TITLE": f"REIP: {lead_values.get('name') or lead_values.get('lead_id')}",
                "NAME": lead_values.get("name"),
                "PHONE": [{"VALUE": lead_values.get("phone"), "VALUE_TYPE": "WORK"}],
                "EMAIL": [{"VALUE": lead_values.get("email"), "VALUE_TYPE": "WORK"}],
                "SOURCE_DESCRIPTION": lead_values.get("source_type"),
                "OPPORTUNITY": lead_values.get("budget_max"),
            }
        }


class YUcrmAdapter(CRMAdapter):
    crm_type = "yucrm"

    def endpoint(self) -> str:
        return f"{self.base_url}/api/v1/leads" if self.base_url else ""

    def build_payload(self, lead_values: dict) -> dict:
        return {
            "client_name": lead_values.get("name"),
            "phone": lead_values.get("phone"),
            "email": lead_values.get("email"),
            "budget_from": lead_values.get("budget_min"),
            "budget_to": lead_values.get("budget_max"),
            "comment": f"Сегмент: {lead_values.get('segment')}, цель: {lead_values.get('purchase_goal')}",
            "utm_source": lead_values.get("utm_source"),
        }


class GenericWebhookAdapter(CRMAdapter):
    crm_type = "generic_webhook"

    def endpoint(self) -> str:
        return self.base_url

    def build_payload(self, lead_values: dict) -> dict:
        mapping = self.field_mapping or {k: k for k in lead_values}
        return {crm_key: lead_values.get(reip_key) for crm_key, reip_key in mapping.items()}
