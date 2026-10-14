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


# --- lead magnets: which are on, the agency's rates, links and requests -----

class LeadMagnetsRequest(BaseModel):
    """Same units as the GET answer: percents, months."""
    enabled: Optional[list[str]] = None
    mortgage_rates_percent: Optional[dict[str, float]] = None
    rental: Optional[dict[str, float]] = None  # season_months, monthly_rent_percent, occupancy_percent

    def stored_units(self) -> tuple[Optional[dict], Optional[dict]]:
        rates = None if self.mortgage_rates_percent is None else {
            k: v / 100 for k, v in self.mortgage_rates_percent.items()}
        rental = None
        if self.rental is not None:
            names = {"season_months": ("season_months", 1), "monthly_rent_percent": ("rate_pct", 100),
                     "occupancy_percent": ("occupancy", 100)}
            rental = {}
            for key, value in self.rental.items():
                stored_key, scale = names.get(key, (key, 1))
                rental[stored_key] = value / scale
        return rates, rental


async def _lm_dto(session, agency_id: uuid.UUID) -> dict:
    from datetime import datetime, timedelta, timezone  # noqa: PLC0415

    from sqlalchemy import func, select  # noqa: PLC0415

    from app.config import config  # noqa: PLC0415
    from app.models.agency import Agency  # noqa: PLC0415
    from app.models.lead import Lead  # noqa: PLC0415
    from app.services.lead_magnets import mortgage_calculator  # noqa: PLC0415
    from app.services.lead_magnets import settings as lm  # noqa: PLC0415

    agency = await session.get(Agency, agency_id)
    since = datetime.now(timezone.utc) - timedelta(days=30)
    source = Lead.buyer_profile["lm_source"].astext
    counts = dict((await session.execute(
        select(source, func.count()).where(
            Lead.agency_id == agency_id, Lead.source_type == "lead_magnet",
            Lead.created_at >= since).group_by(source))).all())
    off = lm.disabled(agency)
    base = f"{config.base_url.rstrip('/')}/lm/{agency_id}"
    programs = lm.programs_for(agency)
    rental = lm.rental_for(agency, agency.base_city)
    return {
        "available": lm.is_available(agency),
        "overview_url": base,
        "tools": [{"slug": slug, "title": title, "description": about, "enabled": slug not in off,
                   "url": f"{base}/{slug}", "leads_30d": int(counts.get(source_key, 0))}
                  for slug, source_key, title, about in lm.TOOLS],
        "mortgage_programs": [
            {"key": key, "name": p.name, "rate_percent": round(p.rate * 100, 2),
             "default_rate_percent": round(mortgage_calculator.MORTGAGE_PROGRAMS[key].rate * 100, 2)}
            for key, p in programs.items()],
        "rental": {"city": agency.base_city, "season_months": rental["season_months"],
                   "monthly_rent_percent": round(rental["rate_pct"] * 100, 3),
                   "occupancy_percent": round(rental["occupancy"] * 100, 1)},
    }


@router.get("/lead-magnets")
async def get_lead_magnets(
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    await require_owner(session, current)
    return await _lm_dto(session, uuid.UUID(current.agency_id))


@router.patch("/lead-magnets")
async def update_lead_magnets(
    req: LeadMagnetsRequest,
    current: CurrentManager = Depends(get_current_manager),
    session=Depends(get_session),
):
    from app.models.agency import Agency  # noqa: PLC0415
    from app.services.lead_magnets import settings as lm  # noqa: PLC0415

    await require_owner(session, current)
    agency_id = uuid.UUID(current.agency_id)
    agency = await session.get(Agency, agency_id)
    settings = dict(agency.settings or {})
    rates, rental = req.stored_units()
    settings[lm.SETTINGS_KEY] = lm.validate_update(
        lm.stored(agency), enabled=req.enabled, mortgage_rates=rates, rental=rental)
    agency.settings = settings
    await session.commit()
    return await _lm_dto(session, agency_id)
