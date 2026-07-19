"""Geo protection: is a region open, partner-served, or blocked. TZ section 28.1."""
from __future__ import annotations

from typing import Optional, TypedDict

import structlog

logger = structlog.get_logger()


class GeoProtectionResult(TypedDict):
    decision: str  # 'allowed' | 'partner_offer' | 'blocked'
    reason: str
    partner_id: Optional[str]
    partner_name: Optional[str]


async def check_geo_protection(city_name: str, region: Optional[str] = None) -> GeoProtectionResult:
    """Decide whether an agency may open sales in a city.

    - allowed: region is open
    - partner_offer: region is served by an active partner (offer the referral deal)
    - blocked: region is reserved with no partner to route to
    """
    from sqlalchemy import select

    from app.database import async_session
    from app.models.protected_geo import ProtectedGeo

    async with async_session() as session:
        stmt = select(ProtectedGeo).where(
            ProtectedGeo.city_name.ilike(f"%{city_name}%"),
            ProtectedGeo.status == "active",
        )
        protection = (await session.execute(stmt)).scalars().first()

        if protection is None:
            return GeoProtectionResult(
                decision="allowed", reason="Region is open", partner_id=None, partner_name=None
            )

        if protection.partner_agency_id:
            from app.models.partner_agency import PartnerAgency

            partner = await session.get(PartnerAgency, protection.partner_agency_id)
            if partner and partner.is_active:
                return GeoProtectionResult(
                    decision="partner_offer",
                    reason=(
                        f"Регион {city_name} обслуживается партнёром {partner.partner_name}. "
                        f"Комиссия: {partner.commission_percent}%."
                    ),
                    partner_id=str(partner.id),
                    partner_name=partner.partner_name,
                )

        return GeoProtectionResult(
            decision="blocked",
            reason=f"Регион {city_name} занят. Свяжитесь с администрацией.",
            partner_id=None,
            partner_name=None,
        )
