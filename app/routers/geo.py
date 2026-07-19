"""Geo management router. TZ sections 13.2 + 28.

POST /api/geo/agencies/{agency_id}/geo:
  1. geo protection check -> blocked (409) | partner_offer (202) | allowed
  2. create the sales geo + reserve the region (protected_geos)
  3. enqueue AI keyword generation (Celery)
"""
from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.database import get_session
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


@router.post("/agencies/{agency_id}/geo", status_code=status.HTTP_201_CREATED)
async def create_geo_location(
    agency_id: uuid.UUID, req: CreateGeoRequest, session=Depends(get_session)
):
    agency = await session.get(Agency, agency_id)
    if agency is None:
        raise NotFoundError("Agency", str(agency_id))

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

    # Reserve the region for this agency.
    session.add(
        ProtectedGeo(
            city_name=req.city_name,
            region=req.region,
            protected_by_agency_id=agency_id,
            status="active",
            protection_radius_km=50,
        )
    )
    await session.commit()

    # Enqueue AI keyword generation (non-blocking).
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
