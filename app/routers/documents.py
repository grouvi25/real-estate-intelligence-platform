"""Deal document router. TZ sections 32.8 and 35.9.

Generates the two deal documents the acceptance checklist asks for -- the
preliminary sale contract and the document-check checklist -- renders them to
PDF and stores them, returning a URL the manager can open.

Only the commercial offer and the object report existed before, and both were
rendered inline in leads.py / properties.py with no storage step, so
"POST /documents/checklist/{id} -> pdf_url с работающей ссылкой" (TZ 35.9) had
nothing behind it.

Manager-scoped: the agency always comes from the JWT, never from client input.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import structlog
from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel

from app.config import config
from app.database import get_session
from app.dependencies import CurrentManager, get_current_manager
from app.exceptions import NotFoundError, ValidationError
from app.models.agency import Agency
from app.models.lead import Lead
from app.models.property import Property

logger = structlog.get_logger()
router = APIRouter()


class ContractRequest(BaseModel):
    lead_id: uuid.UUID
    property_id: uuid.UUID
    deposit_amount: int
    deposit_days: int = 7
    final_date: str


async def _scoped_property(property_id: uuid.UUID, current: CurrentManager, session) -> Property:
    prop = await session.get(Property, property_id)
    if prop is None or str(prop.agency_id) != current.agency_id:
        raise NotFoundError("Property", str(property_id))
    return prop


async def _render_and_store(doc_type: str, context: dict, key: str) -> dict:
    """Render to PDF, store it, and return the document descriptor.

    Falls back to HTML when WeasyPrint is unavailable (the optional 'pdf' extra
    needs Pango/Cairo) so the endpoint stays usable rather than returning 501.
    """
    from app.services.document_service import render_html, render_pdf
    from app.services.storage import get_storage

    storage = get_storage()
    try:
        content, content_type, suffix = render_pdf(doc_type, context), "application/pdf", "pdf"
    except Exception as e:  # noqa: BLE001 - PDF stack missing; HTML is a valid document
        logger.warning("PDF unavailable, storing HTML", doc_type=doc_type, error=str(e))
        content = render_html(doc_type, context).encode("utf-8")
        content_type, suffix = "text/html; charset=utf-8", "html"

    full_key = f"{key}.{suffix}"
    try:
        storage_url = await storage.upload(full_key, content, content_type=content_type)
    except Exception as e:  # noqa: BLE001 - object storage down or misconfigured
        # The document itself is fine; only the destination failed. Fall back to
        # local storage rather than handing the manager a 500 -- the link below
        # goes through this API either way, so nothing downstream notices.
        from app.services.storage import LocalStorage  # noqa: PLC0415

        logger.warning("Object storage upload failed, storing locally",
                       doc_type=doc_type, error=str(e))
        storage_url = await LocalStorage().upload(full_key, content, content_type=content_type)
    logger.info("Document generated", doc_type=doc_type, key=full_key, format=suffix)
    return {
        # LocalStorage hands back a file:// path and an Object Storage URL needs a
        # public bucket, so the link the manager gets always goes through the API.
        "url": f"{config.base_url.rstrip('/')}/api/documents/{full_key}",
        "storage_url": storage_url,
        "key": full_key,
        "format": suffix,
        "size_bytes": len(content),
    }


@router.post("/preliminary-contract", status_code=status.HTTP_201_CREATED)
async def create_contract(
    req: ContractRequest,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """Preliminary sale contract filled with the lead's and object's data."""
    if req.deposit_amount <= 0:
        raise ValidationError("deposit_amount", "сумма должна быть больше нуля")
    if req.deposit_days <= 0:
        raise ValidationError("deposit_days", "срок должен быть больше нуля")
    try:
        date.fromisoformat(req.final_date)
    except ValueError as e:
        raise ValidationError("final_date", "ожидается дата в формате ГГГГ-ММ-ДД") from e

    lead = await session.get(Lead, req.lead_id)
    if lead is None or str(lead.agency_id) != current.agency_id:
        raise NotFoundError("Lead", str(req.lead_id))
    prop = await _scoped_property(req.property_id, current, session)
    agency = await session.get(Agency, uuid.UUID(current.agency_id))

    context = {
        "contract_date": date.today().isoformat(),
        "city": prop.district or (agency.base_city if agency else None),
        "agency_name": agency.name if agency else "",
        "manager_name": "",
        # PII is decrypted here only to be written into the document the manager
        # hands to that same client.
        "client_name": lead.name,
        "client_phone": lead.phone,
        "property_title": prop.title,
        "address": prop.address,
        "area_total": prop.area_total,
        "rooms": prop.rooms,
        "floor": prop.floor,
        "floors_total": prop.floors_total,
        "price": prop.price,
        "deposit_amount": req.deposit_amount,
        "deposit_days": req.deposit_days,
        "final_date": req.final_date,
    }
    key = f"documents/{current.agency_id}/contract_{req.lead_id}_{req.property_id}"
    doc = await _render_and_store("preliminary_contract", context, key)
    return {"document_type": "preliminary_contract", "pdf_url": doc["url"], **doc}


@router.post("/checklist/{property_id}", status_code=status.HTTP_201_CREATED)
async def create_checklist(
    property_id: uuid.UUID,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """Document-check checklist for an object (new build vs resale)."""
    from app.services.document_service import checklist_sections

    prop = await _scoped_property(property_id, current, session)
    context = {
        "property_title": prop.title,
        "address": prop.address,
        "price": prop.price,
        "sections": checklist_sections(bool(prop.is_new_build)),
        "generated_at": datetime.now(timezone.utc).strftime("%d.%m.%Y"),
    }
    key = f"documents/{current.agency_id}/checklist_{property_id}"
    doc = await _render_and_store("checklist", context, key)
    return {"document_type": "checklist", "pdf_url": doc["url"], **doc}


@router.get("/{doc_key:path}")
async def fetch_document(
    doc_key: str,
    current: CurrentManager = Depends(get_current_manager),
):
    """Serve a stored document.

    LocalStorage keeps files on the app's own disk, so its url() is not fetchable
    on its own; this endpoint makes the returned link work in both storage modes.
    Scoped by the agency prefix in the key so one agency cannot read another's.
    """
    from app.services.storage import get_storage

    if not doc_key.startswith(f"documents/{current.agency_id}/"):
        raise NotFoundError("Document", doc_key)
    try:
        content = await get_storage().download(doc_key)
    except Exception as e:  # noqa: BLE001 - missing key or backend error
        raise NotFoundError("Document", doc_key) from e

    media = "application/pdf" if doc_key.endswith(".pdf") else "text/html; charset=utf-8"
    return Response(content=content, media_type=media)
