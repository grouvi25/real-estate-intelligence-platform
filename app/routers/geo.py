"""Geo management router. TZ sections 13.2 + 28.

- GET  /api/geo                          list sales/base geos for current agency (JWT)
- POST /api/geo                          add a city for current agency (JWT)
- POST /api/geo/agencies/{agency_id}/geo onboarding path (no JWT, used internally)

Flow on create: geo protection check -> blocked (409) | partner_offer (202) |
allowed -> create sales geo + reserve region + enqueue AI keyword generation.
"""
from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.database import get_session
from app.dependencies import CurrentManager, get_current_manager
from app.exceptions import AppException, NotFoundError
from app.models.agency import Agency
from app.models.geo_location import GeoLocation
from app.models.protected_geo import ProtectedGeo
from app.services.geo_protection import check_geo_protection

logger = structlog.get_logger()
router = APIRouter()


class CreateGeoRequest(BaseModel):
    city_name: str
    region: str
    market_type: str = "urban"  # urban | resort | suburban
    primary_segments: list[str] = ["family", "investor"]


def _geo_dto(g: GeoLocation) -> dict:
    return {
        "id": str(g.id),
        "city_name": g.city_name,
        "region": g.region,
        "geo_type": g.geo_type,
        "is_active": g.is_active,
        "auto_discovery_enabled": g.auto_discovery_enabled,
        "has_keywords": bool(g.keywords),
    }


async def _create_geo(session, agency_id: uuid.UUID, req: CreateGeoRequest):
    """Shared create logic (protection -> create -> reserve -> keywords)."""
    protection = await check_geo_protection(req.city_name, req.region)
    if protection["decision"] == "blocked":
        raise AppException(
            status_code=status.HTTP_409_CONFLICT, detail=protection["reason"], code="GEO_PROTECTED"
        )
    if protection["decision"] == "partner_offer":
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "status": "partner_offer",
                "message": protection["reason"],
                "partner_id": protection["partner_id"],
                "action": "POST /api/partners/accept",
            },
        )

    geo = GeoLocation(
        agency_id=agency_id,
        city_name=req.city_name,
        region=req.region,
        geo_type="sales",
        market_profile={"type": req.market_type},
        auto_discovery_enabled=True,
    )
    session.add(geo)
    await session.flush()
    session.add(
        ProtectedGeo(
            city_name=req.city_name, region=req.region,
            protected_by_agency_id=agency_id, status="active", protection_radius_km=50,
        )
    )
    await session.commit()

    payload = req.model_dump()
    payload["agency_id"] = str(agency_id)
    from worker.tasks.geo_tasks import generate_keywords_for_geo

    generate_keywords_for_geo.delay(str(geo.id), payload)

    return {
        "geo_id": str(geo.id),
        "status": "discovery_started",
        "geo_protected": True,
        "message": f"Город {req.city_name} добавлен и зарезервирован. Генерация keywords запущена.",
    }


@router.get("/suggest")
async def suggest_cities(
    q: str,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    """Towns matching what has been typed, for the city fields.

    Every screen that needs a city asked the manager to type it out and hope for
    the best, so the database collected «геленджик», «Геленжик» and «г. Геленджик»
    as three different places. Picking from a list makes the name canonical.

    Biased towards where the agency already works: Yandex only matches a prefix
    inside a narrow window, and the agency's own city is the best guess at one.
    """
    from app.models.agency import Agency  # noqa: PLC0415
    from app.services import geocoder  # noqa: PLC0415

    if not geocoder.is_available():
        return {"cities": []}

    agency = await session.get(Agency, uuid.UUID(current.agency_id))
    near = agency.base_city if agency else None
    return {"cities": await geocoder.suggest_cities(q, near=near)}


@router.get("")
async def list_geo(
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    stmt = (
        select(GeoLocation)
        .where(GeoLocation.agency_id == uuid.UUID(current.agency_id))
        .order_by(GeoLocation.geo_type, GeoLocation.city_name)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return {"count": len(rows), "geo": [_geo_dto(g) for g in rows]}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_geo(
    req: CreateGeoRequest,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    return await _create_geo(session, uuid.UUID(current.agency_id), req)


@router.post("/agencies/{agency_id}/geo", status_code=status.HTTP_201_CREATED)
async def create_geo_location(
    agency_id: uuid.UUID, req: CreateGeoRequest, session=Depends(get_session)
):
    agency = await session.get(Agency, agency_id)
    if agency is None:
        raise NotFoundError("Agency", str(agency_id))
    return await _create_geo(session, agency_id, req)
