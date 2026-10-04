"""Avito catalogue sync: status and a manual run. ТЗ «Avito + фильтрация» v1, 1.12."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.database import get_session
from app.dependencies import CurrentManager, get_current_manager, require_owner

router = APIRouter()


@router.get("/status")
async def avito_status(current: CurrentManager = Depends(get_current_manager),
                       session=Depends(get_session)):
    from app.models.agency import Agency
    from app.models.property import Property
    from app.services.avito_sync import credentials_for

    agency_id = uuid.UUID(current.agency_id)
    agency = await session.get(Agency, agency_id)
    base = (Property.agency_id == agency_id) & (Property.source_system == "avito")
    last = await session.scalar(select(func.max(Property.avito_synced_at)).where(base))
    return {
        "configured": bool(agency is not None and await credentials_for(session, agency)),
        "total": await session.scalar(select(func.count(Property.id)).where(base)) or 0,
        "active": await session.scalar(select(func.count(Property.id)).where(
            base, Property.status == "active")) or 0,
        "last_synced_at": last.isoformat() if last else None,
    }


@router.post("/sync")
async def avito_sync(current: CurrentManager = Depends(get_current_manager),
                     session=Depends(get_session)):
    """Queue a sync now instead of waiting for the hourly one (owner only)."""
    await require_owner(session, current)
    from worker.tasks.avito_tasks import sync_avito

    task = sync_avito.delay()
    return {"task_id": task.id, "status": "queued"}
