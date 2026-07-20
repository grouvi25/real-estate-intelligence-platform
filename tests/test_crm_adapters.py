"""CRM adapter tests (Signal Bus addendum). build_payload() is pure."""
from app.services.crm import SUPPORTED_CRMS, build_crm_adapter

LEAD = {
    "name": "Иван Петров", "phone": "+79001234567", "email": "i@example.com",
    "budget_min": 5_000_000, "budget_max": 8_000_000, "segment": "family",
    "purchase_goal": "own", "source_type": "signal", "utm_source": "vk",
    "lead_id": "abc-123",
}


def test_registry_supported():
    assert set(SUPPORTED_CRMS) == {"topnlab", "amocrm", "bitrix24", "yucrm"}
    assert build_crm_adapter("unknown") is None


def test_topnlab_payload_and_endpoint():
    a = build_crm_adapter("topnlab", base_url="https://t.example.com/")
    assert a.endpoint() == "https://t.example.com/api/leads"
    p = a.build_payload(LEAD)
    assert p["phone"] == "+79001234567"
    assert p["budget"] == 8_000_000
    assert p["external_id"] == "abc-123"


def test_amocrm_payload_shape():
    a = build_crm_adapter("amocrm", base_url="https://x.amocrm.ru", api_key="tok")
    assert a.endpoint().endswith("/api/v4/leads/complex")
    assert a.headers()["Authorization"] == "Bearer tok"
    p = a.build_payload(LEAD)
    assert isinstance(p, list)
    contact = p[0]["_embedded"]["contacts"][0]
    assert contact["custom_fields_values"][0]["values"][0]["value"] == "+79001234567"


def test_bitrix24_payload_and_no_auth_header():
    a = build_crm_adapter("bitrix24", base_url="https://x.bitrix24.ru/rest/1/token")
    assert a.endpoint().endswith("/crm.lead.add.json")
    assert a.headers() == {}
    p = a.build_payload(LEAD)
    assert p["fields"]["PHONE"][0]["VALUE"] == "+79001234567"
    assert p["fields"]["OPPORTUNITY"] == 8_000_000


def test_yucrm_payload():
    a = build_crm_adapter("yucrm", base_url="https://y.example.com")
    p = a.build_payload(LEAD)
    assert p["client_name"] == "Иван Петров"
    assert p["budget_to"] == 8_000_000
    assert p["utm_source"] == "vk"
