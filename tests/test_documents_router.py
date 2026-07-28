"""Deal document endpoint tests (need PostgreSQL). TZ 32.8 / 35.9.

TZ 35.9 asks for `POST /documents/checklist/{id} -> pdf_url с работающей ссылкой`
and a preliminary contract carrying the lead's and object's data. Neither
template nor router existed before.
"""
import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL"
)


async def _fixture(s, *, is_new_build=False):
    from app.models.agency import Agency
    from app.models.lead import Lead
    from app.models.property import Property

    agency = Agency(name="Docs Agency", base_city="Геленджик")
    s.add(agency)
    await s.flush()

    lead = Lead(agency_id=agency.id, source_type="signal")
    lead.name = "Иван Петров"
    lead.phone = "+79991234567"
    prop = Property(
        agency_id=agency.id, title="2-к квартира на Толстом мысу", price=9_500_000,
        address="ул. Морская, 12", rooms=2, area_total=64.5, floor=4, floors_total=9,
        is_new_build=is_new_build,
    )
    s.add_all([lead, prop])
    await s.commit()
    return agency, lead, prop


def _current(agency):
    from app.dependencies import CurrentManager

    return CurrentManager(manager_id=str(uuid.uuid4()), agency_id=str(agency.id))


@pytest.mark.asyncio
async def test_contract_carries_lead_and_property_data():
    from app.database import async_session, run_migrations
    from app.routers.documents import ContractRequest, create_contract, fetch_document
    from app.services.storage import get_storage

    await run_migrations()
    async with async_session() as s:
        agency, lead, prop = await _fixture(s)
        current = _current(agency)

    async with async_session() as s:
        res = await create_contract(
            ContractRequest(lead_id=lead.id, property_id=prop.id,
                            deposit_amount=300_000, deposit_days=5, final_date="2026-09-01"),
            current=current, session=s)

    assert res["document_type"] == "preliminary_contract"
    assert res["size_bytes"] > 0
    # The link is served by the API, so it works with either storage backend.
    assert res["pdf_url"].endswith(res["key"])
    assert f"/api/documents/documents/{agency.id}/" in res["pdf_url"]

    body = (await get_storage().download(res["key"])).decode("utf-8", errors="ignore")
    if res["format"] == "html":  # PDF is opaque; assert on the rendered source
        assert "Иван Петров" in body
        assert "2-к квартира на Толстом мысу" in body
        assert "300 000" in body and "2026-09-01" in body

    served = await fetch_document(res["key"], current=current)
    assert served.status_code == 200


@pytest.mark.asyncio
async def test_checklist_switches_sections_for_new_build_and_resale():
    from app.database import async_session, run_migrations
    from app.routers.documents import create_checklist
    from app.services.storage import get_storage

    await run_migrations()
    async with async_session() as s:
        agency_new, _, prop_new = await _fixture(s, is_new_build=True)
        current_new = _current(agency_new)
    async with async_session() as s:
        agency_old, _, prop_old = await _fixture(s, is_new_build=False)
        current_old = _current(agency_old)

    async with async_session() as s:
        new_doc = await create_checklist(prop_new.id, current=current_new, session=s)
        old_doc = await create_checklist(prop_old.id, current=current_old, session=s)

    assert new_doc["document_type"] == "checklist"
    if new_doc["format"] == "html":
        new_body = (await get_storage().download(new_doc["key"])).decode("utf-8")
        old_body = (await get_storage().download(old_doc["key"])).decode("utf-8")
        assert "Эскроу-счёт" in new_body and "Эскроу-счёт" not in old_body
        assert "Согласие супруга" in old_body and "Согласие супруга" not in new_body
        # Common checks appear in both.
        assert "Выписка из ЕГРН" in new_body and "Выписка из ЕГРН" in old_body


@pytest.mark.asyncio
async def test_documents_are_scoped_to_the_token_agency():
    from app.database import async_session, run_migrations
    from app.exceptions import NotFoundError
    from app.models.agency import Agency
    from app.routers.documents import ContractRequest, create_checklist, create_contract, fetch_document

    await run_migrations()
    async with async_session() as s:
        agency, lead, prop = await _fixture(s)
        other = Agency(name="Other Docs Agency", base_city="Сочи")
        s.add(other)
        await s.commit()
        current, stranger = _current(agency), _current(other)

    async with async_session() as s:
        with pytest.raises(NotFoundError):
            await create_checklist(prop.id, current=stranger, session=s)
        with pytest.raises(NotFoundError):
            await create_contract(
                ContractRequest(lead_id=lead.id, property_id=prop.id,
                                deposit_amount=1000, final_date="2026-09-01"),
                current=stranger, session=s)

        doc = await create_checklist(prop.id, current=current, session=s)

    # Another agency cannot read a stored document by guessing its key.
    with pytest.raises(NotFoundError):
        await fetch_document(doc["key"], current=stranger)


@pytest.mark.asyncio
async def test_contract_validates_its_input():
    from app.database import async_session, run_migrations
    from app.exceptions import ValidationError
    from app.routers.documents import ContractRequest, create_contract

    await run_migrations()
    async with async_session() as s:
        agency, lead, prop = await _fixture(s)
        current = _current(agency)

    async with async_session() as s:
        for bad in (
            ContractRequest(lead_id=lead.id, property_id=prop.id,
                            deposit_amount=0, final_date="2026-09-01"),
            ContractRequest(lead_id=lead.id, property_id=prop.id,
                            deposit_amount=1000, deposit_days=0, final_date="2026-09-01"),
            ContractRequest(lead_id=lead.id, property_id=prop.id,
                            deposit_amount=1000, final_date="01.09.2026"),
        ):
            with pytest.raises(ValidationError):
                await create_contract(bad, current=current, session=s)


def test_checklist_sections_are_not_empty():
    """Pure helper — runs without a database."""
    from app.services.document_service import checklist_sections

    for is_new in (True, False):
        sections = checklist_sections(is_new)
        assert len(sections) == 2
        assert all(s["points"] for s in sections)


def test_all_four_templates_render():
    from app.services.document_service import TEMPLATES, render_html

    assert set(TEMPLATES) == {
        "commercial_offer", "object_report", "preliminary_contract", "checklist"
    }
    html = render_html("checklist", {
        "property_title": "Дом", "sections": [{"title": "Раздел", "points": ["Пункт"]}],
        "generated_at": "01.01.2026",
    })
    assert "Пункт" in html
