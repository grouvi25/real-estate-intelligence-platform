"""CRM export tests (TZ 32 + Signal Bus addendum §4)."""
from types import SimpleNamespace

import pytest

from app.services.crm_export import DEFAULT_FIELD_MAPPING, build_crm_payload


class _Lead(SimpleNamespace):
    """A qualified lead with consent — the only kind that is ever exported."""

    def __init__(self, **kw):
        super().__init__(**{
            "id": "11111111-1111-4111-8111-111111111111",
            "agency_id": "22222222-2222-4222-8222-222222222222",
            "consent_given": True, "crm_deal_id": None,
            "name": "Иван Петров", "phone": "+79001234567", "email": "i@example.com",
            "telegram_username": "ivan", "budget_min": 5_000_000, "budget_max": 8_000_000,
            "segment": "family", "purchase_goal": "own", "status": "qualified",
            "intent_score": 80, "source_type": "lead_magnet", "source_platform": "web",
            "utm_source": "vk", "utm_medium": "cpc", "utm_campaign": "spring",
            **kw,
        })


class _Agency(SimpleNamespace):
    def __init__(self, **kw):
        super().__init__(**{
            "crm_export_enabled": True, "crm_webhook_url": "https://hook.example/crm",
            "crm_field_mapping": None, "crm_type": "generic_webhook", **kw,
        })


class _Session:
    """Enough session for the export path: get() and commit()."""

    def __init__(self, agency=None):
        self._agency = agency

    async def get(self, model, pk):
        return self._agency

    async def commit(self):
        return None


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


# --- the connector layer was dead code -------------------------------------

@pytest.mark.asyncio
async def test_a_configured_connector_is_used_instead_of_the_webhook(monkeypatch):
    """agency_crm_config existed, the four vendor adapters existed, and nothing
    connected them: an agency on Topnlab got the generic webhook and its adapter
    was never called. Addendum §4 and its acceptance list say otherwise."""
    from app.services import crm_export
    from app.services.crm.adapters import TopnlabAdapter

    calls = {}

    class _Cfg:
        crm_type = "topnlab"
        base_url = "https://crm.example"
        api_key = "k"
        config: dict = {}
        field_mapping: dict = {}

    async def cfg(session, agency_id):
        return _Cfg()

    async def export(self, values):
        calls["crm"] = self.crm_type
        calls["lead"] = values.get("lead_id")
        return {"exported": True, "crm": self.crm_type, "crm_deal_id": "DEAL-7"}

    monkeypatch.setattr(crm_export, "_active_config", cfg)
    monkeypatch.setattr(TopnlabAdapter, "export", export)

    lead = _Lead()
    session = _Session()
    result = await crm_export.export_lead_to_crm(session, lead)

    assert calls["crm"] == "topnlab"
    assert result["exported"] is True
    # The one link that lets revenue be traced back to the signal.
    assert lead.crm_deal_id == "DEAL-7"


@pytest.mark.asyncio
async def test_without_a_connector_the_webhook_behaves_exactly_as_before(monkeypatch):
    """The addendum requires the generic path to stay identical."""
    from app.services import crm_export

    async def no_cfg(session, agency_id):
        return None

    monkeypatch.setattr(crm_export, "_active_config", no_cfg)

    posted = {}

    class _Resp:
        status_code = 200

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            posted["url"] = url
            posted["json"] = json
            return _Resp()

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _Client())

    result = await crm_export.export_lead_to_crm(_Session(agency=_Agency()), _Lead())

    assert result["exported"] is True
    assert posted["url"] == "https://hook.example/crm"
    assert posted["json"]["crm_type"] == "generic_webhook"


@pytest.mark.asyncio
async def test_a_closed_deal_is_reported_back(monkeypatch):
    """CRMConnector has two halves; only the first was ever called, so a deal
    closed in REIP never reached the CRM that opened it."""
    from app.services import crm_export
    from app.services.crm.adapters import AmoCrmAdapter

    seen = {}

    class _Cfg:
        crm_type = "amocrm"
        base_url = "https://amo.example"
        api_key = "k"
        config: dict = {}
        field_mapping: dict = {}

    async def cfg(session, agency_id):
        return _Cfg()

    async def push(self, values, outcome):
        seen["deal_id"] = values.get("crm_deal_id")
        seen["outcome"] = outcome.outcome
        return {"exported": True}

    monkeypatch.setattr(crm_export, "_active_config", cfg)
    monkeypatch.setattr(AmoCrmAdapter, "push_outcome", push)

    lead = _Lead()
    lead.crm_deal_id = "DEAL-7"

    class _Outcome:
        outcome = "deal_done"
        deal_amount = 8_500_000
        commission_amount = 300_000
        deal_closed_at = None

    result = await crm_export.push_outcome_to_crm(_Session(), lead, _Outcome())

    assert result["exported"] is True
    assert seen == {"deal_id": "DEAL-7", "outcome": "deal_done"}


@pytest.mark.parametrize("body,expected", [
    ({"id": 42}, "42"),
    ({"deal_id": "D-1"}, "D-1"),
    ({"_embedded": {"leads": [{"id": 900}]}}, "900"),
    ({"result": {"id": "B-5"}}, "B-5"),
    ({"status": "ok"}, None),
])
def test_the_vendor_deal_id_is_recognised(body, expected):
    """Four CRMs, four names for the same thing."""
    from app.services.crm.adapters import TopnlabAdapter

    assert TopnlabAdapter().extract_deal_id(body) == expected
