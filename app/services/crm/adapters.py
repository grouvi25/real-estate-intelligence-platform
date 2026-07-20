"""Vendor CRM adapters: Topnlab, amoCRM, Bitrix24, YUcrm. Signal Bus addendum.

Each adapter targets its vendor's documented lead-create endpoint and payload
shape. Credentials/base URL come from agency_crm_config. build_payload is pure.
"""
from __future__ import annotations

from app.services.crm.base import CRMAdapter


class TopnlabAdapter(CRMAdapter):
    crm_type = "topnlab"

    def endpoint(self) -> str:
        return f"{self.base_url}/api/leads" if self.base_url else ""

    def build_payload(self, lead_values: dict) -> dict:
        return {
            "name": lead_values.get("name"),
            "phone": lead_values.get("phone"),
            "email": lead_values.get("email"),
            "budget": lead_values.get("budget_max"),
            "segment": lead_values.get("segment"),
            "source": lead_values.get("source_type"),
            "external_id": lead_values.get("lead_id"),
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
