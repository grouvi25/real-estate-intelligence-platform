"""The agency's own subscription, as the cabinet shows it. ТЗ «SaaS-слой» v1.

Reachable even when the agency is blocked (billing.ALWAYS_ALLOWED_PATHS): an
owner locked out of everything else must still be able to see why and until when.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.database import get_session
from app.dependencies import CurrentManager, get_current_manager
from app.exceptions import AppException

router = APIRouter()


@router.get("/status")
async def subscription_status(
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    from app.models.agency import Agency
    from app.models.geo_location import GeoLocation
    from app.models.manager import Manager
    from app.services.billing import status_payload

    agency_id = uuid.UUID(current.agency_id)
    agency = await session.get(Agency, agency_id)
    if agency is None:
        raise AppException(404, "Агентство не найдено", "NOT_FOUND")
    payload = status_payload(agency)
    payload["usage"] = {
        "managers": await session.scalar(select(func.count(Manager.id)).where(
            Manager.agency_id == agency_id, Manager.is_active.is_(True))) or 0,
        "cities": await session.scalar(select(func.count(GeoLocation.id)).where(
            GeoLocation.agency_id == agency_id)) or 0,
    }
    return payload
