"""Public platform endpoints for the sales landing. ТЗ «SaaS-слой» v1, раздел 7.3.

No authentication by design, so both are rate-limited, and neither names the
agency that holds a city.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.database import get_session
from app.services.rate_limit import rate_limit

router = APIRouter()


@router.get("/city-check", dependencies=[Depends(rate_limit("city_check", limit=30, window=60))])
async def city_check(city: str = Query(..., min_length=2, max_length=100), session=Depends(get_session)):
    from app.services.onboarding import check_city_availability

    check = await check_city_availability(session, city)
    return {"available": check.available, "city": check.city, "reason": check.reason}


@router.get("/cities/taken", dependencies=[Depends(rate_limit("cities_taken", limit=30, window=60))])
async def cities_taken(session=Depends(get_session)):
    from app.services.onboarding import taken_cities

    names = await taken_cities(session)
    return {"taken_cities": names, "total_taken": len(names)}
