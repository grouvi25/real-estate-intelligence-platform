"""Properties router: list + update. TZ section 32 (price-change rematch).

All endpoints require a manager JWT and are scoped to the manager's agency.
When a property's price changes, matching is re-run in the background so leads
that now fit are surfaced (rematch_on_price_change).
"""
from __future__ import annotations

import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel
from sqlalchemy import select

from app.database import get_session
from app.dependencies import CurrentManager, get_current_manager
from app.exceptions import NotFoundError, ValidationError
from app.models.property import Property

logger = structlog.get_logger()
router = APIRouter()

PROPERTY_STATUSES = {"active", "reserved", "sold", "archived", "draft"}
MAX_PAGE = 200


class UpdatePropertyRequest(BaseModel):
    price: Optional[int] = None
    status: Optional[str] = None
    title: Optional[str] = None
    description_original: Optional[str] = None


def _property_summary(prop: Property) -> dict:
    return {
        "id": str(prop.id),
        "title": prop.title,
        "price": prop.price,
        "rooms": prop.rooms,
        "area_total": prop.area_total,
        "district": prop.district,
        "status": prop.status,
        "deal_type": prop.deal_type,
    }


@router.get("")
async def list_properties(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    limit = min(max(limit, 1), MAX_PAGE)
    offset = max(offset, 0)
    stmt = select(Property).where(Property.agency_id == uuid.UUID(current.agency_id))
    if status is not None:
        stmt = stmt.where(Property.status == status)
    stmt = stmt.order_by(Property.created_at.desc()).limit(limit).offset(offset)
    rows = (await session.execute(stmt)).scalars().all()
    return {"count": len(rows), "properties": [_property_summary(p) for p in rows]}


async def _get_scoped_property(property_id: uuid.UUID, current: CurrentManager, session) -> Property:
    prop = await session.get(Property, property_id)
    if prop is None or str(prop.agency_id) != current.agency_id:
        raise NotFoundError("Property", str(property_id))
    return prop


@router.patch("/{property_id}")
async def update_property(
    property_id: uuid.UUID,
    req: UpdatePropertyRequest,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """Update a property. A price change triggers a background rematch."""
    if req.status is not None and req.status not in PROPERTY_STATUSES:
        raise ValidationError("status", f"недопустимый статус: {req.status}")

    prop = await _get_scoped_property(property_id, current, session)
    old_price = prop.price
    # TZ 32.4: only a price DROP of >= 5% triggers a re-match.
    price_dropped = (
        req.price is not None and old_price and req.price < old_price
        and (old_price - req.price) / old_price >= 0.05
    )

    if req.price is not None:
        prop.price = req.price
        if prop.area_total:
            prop.price_per_sqm = int(req.price / prop.area_total)
    if req.status is not None:
        prop.status = req.status
    if req.title is not None:
        prop.title = req.title
    if req.description_original is not None:
        prop.description_original = req.description_original
    await session.commit()

    if price_dropped:
        from worker.tasks.matching_tasks import rematch_on_price_change

        rematch_on_price_change.delay(str(prop.id), old_price, req.price)
        logger.info("Price dropped >=5%, rematch queued", property_id=str(prop.id),
                    old_price=old_price, new_price=req.price)

    return {"id": str(prop.id), "price": prop.price, "status": prop.status,
            "price_changed": price_dropped}


@router.get("/{property_id}/report")
async def property_report(
    property_id: uuid.UUID,
    format: str = "html",
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """Render an object report. ?format=html (default) or pdf."""
    from app.services.document_service import render_html, render_pdf

    prop = await _get_scoped_property(property_id, current, session)
    context = {
        "title": prop.title,
        "price": prop.price,
        "address": prop.address,
        "district": prop.district,
        "rooms": prop.rooms,
        "area_total": prop.area_total,
        "floor": prop.floor,
        "floors_total": prop.floors_total,
        "description": prop.description_original,
    }
    if format == "pdf":
        pdf = render_pdf("object_report", context)
        return Response(content=pdf, media_type="application/pdf")
    return HTMLResponse(content=render_html("object_report", context))


class GenerateListingRequest(BaseModel):
    platform: str = "avito"
    target_segment: Optional[str] = None
    tone: str = "professional"


@router.post("/{property_id}/generate-listing")
async def generate_listing(
    property_id: uuid.UUID,
    req: GenerateListingRequest,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """AI-generate a sales listing text for a property (TZ 27 listing_generator)."""
    from app.prompts.listing_generator import SYSTEM_PROMPT_LISTING, USER_PROMPT_LISTING
    from app.services.ai_service import AIService, safe_ai_parse

    prop = await _get_scoped_property(property_id, current, session)
    property_data = (
        f"{prop.title}; {prop.rooms or '—'}-комн.; {prop.area_total or '—'} м²; "
        f"район {prop.district or '—'}; цена {prop.price or '—'} ₽; "
        f"{prop.description_original or ''}"
    )
    seg = req.target_segment or (prop.target_segments[0] if prop.target_segments else "family")
    advantages = ", ".join((prop.ai_analysis or {}).get("strengths", []) or [])

    ai = AIService()
    try:
        res = await ai.complete(
            SYSTEM_PROMPT_LISTING,
            USER_PROMPT_LISTING.format(
                platform=req.platform, property_data=property_data, target_segment=seg,
                key_advantages=advantages or "—", tone_preference=req.tone),
            "listing_generator", agency_id=current.agency_id)
    finally:
        await ai.close()
    return {"listing": safe_ai_parse(res, {"text": res})}


@router.get("/{property_id}")
async def get_property(
    property_id: uuid.UUID,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """Fetch one object. The Mini App used to pull the whole list and search it."""
    return _property_summary(await _get_scoped_property(property_id, current, session))
