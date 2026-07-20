"""CRM export payload tests (TZ 32). build_crm_payload is pure."""
from types import SimpleNamespace

from app.services.crm_export import DEFAULT_FIELD_MAPPING, build_crm_payload


def _fake_lead():
    return SimpleNamespace(
        id="11111111-1111-4111-8111-111111111111",
        name="Иван Петров", phone="+79001234567", email="i@example.com",
        telegram_username="ivan", budget_min=5_000_000, budget_max=8_000_000,
        segment="family", purchase_goal="own", status="qualified", intent_score=80,
        source_type="lead_magnet", source_platform="web",
        utm_source="vk", utm_medium="cpc", utm_campaign="spring",
    )


def test_default_mapping_payload():
    payload = build_crm_payload(_fake_lead(), None)
    assert set(payload.keys()) == set(DEFAULT_FIELD_MAPPING.keys())
    assert payload["name"] == "Иван Петров"
    assert payload["phone"] == "+79001234567"
    assert payload["utm_campaign"] == "spring"
    assert payload["source"] == "lead_magnet"


def test_custom_mapping_payload():
    mapping = {"ФИО": "name", "Телефон": "phone", "Бюджет": "budget_max"}
    payload = build_crm_payload(_fake_lead(), mapping)
    assert payload == {"ФИО": "Иван Петров", "Телефон": "+79001234567", "Бюджет": 8_000_000}


def test_mapping_unknown_field_is_none():
    payload = build_crm_payload(_fake_lead(), {"x": "nonexistent_field"})
    assert payload == {"x": None}
