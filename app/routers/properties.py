"""Properties router: list + update. TZ section 32 (price-change rematch).

All endpoints require a manager JWT and are scoped to the manager's agency.
When a property's price changes, matching is re-run in the background so leads
that now fit are surfaced (rematch_on_price_change).
"""
from __future__ import annotations

import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, File, Form, UploadFile
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
MAX_IMPORT_BYTES = 10_000_000
# Enough to show the pattern of what went wrong without returning a novel.
MAX_IMPORT_ERRORS = 50


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
        # The nightly sweep compares against this, so a re-match done here is not
        # repeated tonight.
        prop.last_rematch_price = req.price
        await session.commit()
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
    """One property, in full.

    The list needs a headline; the card needs the rest. This was answering with
    the list shape, so the card asked for an address, a floor and a price per
    square metre and quietly rendered nothing where each should have been.
    """
    prop = await _get_scoped_property(property_id, current, session)
    city = None
    if prop.geo_location_id:
        from app.models.geo_location import GeoLocation  # noqa: PLC0415

        geo = await session.get(GeoLocation, prop.geo_location_id)
        city = geo.city_name if geo else None
    return {
        **_property_summary(prop),
        "address": prop.address,
        "city_name": city,
        "price_per_sqm": prop.price_per_sqm,
        "floor": prop.floor,
        "floors_total": prop.floors_total,
        "area_living": prop.area_living,
        "property_type": prop.property_type,
        "developer": prop.developer,
        "year_built": prop.year_built,
        "is_new_build": prop.is_new_build,
        "readiness_status": prop.readiness_status,
        "amenities": prop.amenities or [],
        "target_segments": prop.target_segments or [],
        "description_original": prop.description_original,
        "source_url": prop.source_url,
        "images": prop.images or [],
        "ai_analysis": prop.ai_analysis or {},
    }


@router.post("/import")
async def import_properties(
    file: UploadFile = File(...),
    dry_run: bool = Form(default=False),
    geo_location_id: Optional[uuid.UUID] = Form(default=None),
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """Bulk-load the agency catalogue from CSV or XLSX.

    Matching, pitches, offers and the funnel all read from properties, so an
    empty catalogue leaves the buyer half of the system with nothing to offer.
    Agencies keep their inventory in spreadsheets, and this is how it gets in
    without a developer.

    `dry_run` reports exactly what would happen without writing, so a bad column
    mapping is visible before it reaches the database. Rows are matched on
    source_url when present, otherwise on (title, address), which makes
    re-uploading a corrected file an update rather than a duplicate.
    """
    from app.services.property_import import (
        ImportResult, RowError, map_row, read_rows, unmapped_columns, validate_row,
    )

    raw = await file.read()
    if not raw:
        raise ValidationError("file", "файл пуст")
    if len(raw) > MAX_IMPORT_BYTES:
        raise ValidationError("file", f"файл больше {MAX_IMPORT_BYTES // 1_000_000} МБ")

    try:
        rows, headers = read_rows(raw, file.filename or "catalogue.csv")
    except ValueError as e:
        raise ValidationError("file", str(e)) from e
    if not rows:
        raise ValidationError("file", "в файле нет строк с данными")

    agency_id = uuid.UUID(current.agency_id)
    result = ImportResult(unmapped_columns=unmapped_columns(headers))

    for offset, row in enumerate(rows):
        row_number = offset + 2  # 1-based, and the header occupies row 1
        mapped = map_row(row, headers)
        problem = validate_row(mapped)
        if problem:
            result.skipped += 1
            if len(result.errors) < MAX_IMPORT_ERRORS:
                result.errors.append(RowError(row=row_number, message=problem))
            continue

        existing = None
        if mapped.get("source_url"):
            existing = await session.scalar(
                select(Property).where(Property.agency_id == agency_id,
                                       Property.source_url == mapped["source_url"])
            )
        else:
            existing = await session.scalar(
                select(Property).where(Property.agency_id == agency_id,
                                       Property.title == mapped["title"],
                                       Property.address == mapped.get("address"))
            )

        if existing is not None:
            result.updated += 1
            if not dry_run:
                for key, value in mapped.items():
                    setattr(existing, key, value)
                if geo_location_id:
                    existing.geo_location_id = geo_location_id
        else:
            result.created += 1
            if not dry_run:
                session.add(Property(agency_id=agency_id, geo_location_id=geo_location_id,
                                     **mapped))

    if dry_run:
        await session.rollback()
    else:
        await session.commit()

    logger.info("Property import", agency_id=str(agency_id), dry_run=dry_run,
                created=result.created, updated=result.updated, skipped=result.skipped)
    return {"dry_run": dry_run, **result.as_dict()}
