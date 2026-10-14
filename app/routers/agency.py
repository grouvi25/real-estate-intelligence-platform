"""Agency-wide signal filter. ТЗ «Сигналы» v1.0, апгрейд B, раздел 6.3.

GET   /api/agency/signal-filter  which categories the signal list opens with,
                                 plus the competitor names behind «Конкуренты»
PATCH /api/agency/signal-filter  change them (owner)

The ТЗ path is /api/v1/agency/signal-filter; REIP has no /v1 prefix.
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.database import get_session
from app.dependencies import CurrentManager, get_current_manager, require_owner
from app.exceptions import ValidationError
from app.services.signal_classifier import CATEGORIES, CATEGORY_RU, forget_competitors

router = APIRouter()

MAX_COMPETITORS = 100


class SignalFilterRequest(BaseModel):
    enabled_cats: Optional[list[str]] = None
    competitor_names: Optional[list[str]] = None


async def _dto(session, agency_id: uuid.UUID) -> dict:
    from app.models.agency import Agency  # noqa: PLC0415
    from app.models.signal import AgencySignalFilter  # noqa: PLC0415
    from app.services.discovery.settings import (  # noqa: PLC0415
        AUTO_COMPETITORS_KEY,
        MANUAL_COMPETITORS_KEY,
    )

    row = await session.get(AgencySignalFilter, agency_id)
    agency = await session.get(Agency, agency_id)
    settings = (agency.settings if agency else None) or {}
    return {
        "enabled_cats": list(row.enabled_cats) if row else list(CATEGORIES),
        "categories": [{"key": c, "label": CATEGORY_RU[c]} for c in CATEGORIES],
        "competitor_names": list(settings.get(MANUAL_COMPETITORS_KEY) or []),
        "competitors_found": list(settings.get(AUTO_COMPETITORS_KEY) or []),
    }


@router.get("/signal-filter")
async def get_signal_filter(
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    return await _dto(session, uuid.UUID(current.agency_id))


@router.patch("/signal-filter")
async def update_signal_filter(
    req: SignalFilterRequest,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    from app.models.agency import Agency  # noqa: PLC0415
    from app.models.signal import AgencySignalFilter  # noqa: PLC0415
    from app.services.discovery.settings import MANUAL_COMPETITORS_KEY  # noqa: PLC0415

    await require_owner(session, current)
    agency_id = uuid.UUID(current.agency_id)
    if req.enabled_cats is not None:
        cats = [c for c in CATEGORIES if c in set(req.enabled_cats)]
        unknown = set(req.enabled_cats) - set(CATEGORIES)
        if unknown or not cats:
            raise ValidationError("enabled_cats", "выберите хотя бы одну категорию из списка"
                                  if not unknown else f"недопустимая категория: {', '.join(sorted(unknown))}")
        row = await session.get(AgencySignalFilter, agency_id)
        if row is None:
            session.add(AgencySignalFilter(agency_id=agency_id, enabled_cats=cats))
        else:
            row.enabled_cats = cats
    if req.competitor_names is not None:
        names, seen = [], set()
        for name in req.competitor_names:
            clean = " ".join(str(name).split())[:100]
            if len(clean) >= 3 and clean.lower() not in seen:
                seen.add(clean.lower())
                names.append(clean)
        agency = await session.get(Agency, agency_id)
        settings = dict(agency.settings or {})
        settings[MANUAL_COMPETITORS_KEY] = names[:MAX_COMPETITORS]
        agency.settings = settings
        forget_competitors(agency_id)
    await session.commit()
    return await _dto(session, agency_id)
