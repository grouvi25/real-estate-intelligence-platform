"""Turning a paying request into a working agency. ТЗ «SaaS-слой» v1, раздел 5.

scripts/create_agency.py stays for manual use; this is the same thing done from
the operator's commands and the operator API, with the plan's limits and prices,
the subscription dates and a billing record attached.
"""
from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import Text, func, select, update

from app.config import config

logger = structlog.get_logger()

MONTH = timedelta(days=30)


class OnboardingError(Exception):
    """Something the operator has to resolve; the message says what, in Russian."""


def normalize_city(name: str) -> str:
    """«г. Геленджик » -> «геленджик»: what two spellings of one town share."""
    text = re.sub(r"^\s*(г\.|город)\s*", "", (name or "").strip(), flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip().lower().replace("ё", "е")


@dataclass
class CityCheck:
    available: bool
    city: str
    reason: Optional[str] = None


async def check_city_availability(session, city_name: str) -> CityCheck:
    """ТЗ 5.2: is a city still free? Taken = reserved (protected_geos) or already
    worked by an agency. The whole name is compared, not a substring: «Сочи»
    must not come back taken because someone has «Сочи-Адлер»."""
    from app.models.geo_location import GeoLocation  # noqa: PLC0415
    from app.models.protected_geo import ProtectedGeo  # noqa: PLC0415

    wanted = normalize_city(city_name)
    if len(wanted) < 2:
        return CityCheck(False, city_name.strip(), "Укажите название города")
    display = city_name.strip()
    reserved = (await session.execute(select(ProtectedGeo.city_name).where(
        ProtectedGeo.status == "active"))).scalars().all()
    worked = (await session.execute(select(GeoLocation.city_name).where(
        GeoLocation.is_active.is_(True)))).scalars().all()
    if any(normalize_city(c) == wanted for c in [*reserved, *worked]):
        return CityCheck(False, display, f"Город {display} уже подключён другим агентством.")
    return CityCheck(True, display)


async def taken_cities(session) -> list[str]:
    """Distinct taken city names, without the agencies (ТЗ 7.3, public)."""
    from app.models.geo_location import GeoLocation  # noqa: PLC0415

    names = (await session.execute(select(GeoLocation.city_name).where(
        GeoLocation.is_active.is_(True)))).scalars().all()
    seen: dict[str, str] = {}
    for name in names:
        seen.setdefault(normalize_city(name), name.strip())
    return sorted(seen.values())


def invite_link(agency, bot_username: Optional[str] = None) -> str:
    bot = bot_username or agency.telegram_bot_username or config.telegram_bot_username
    return f"https://t.me/{bot}?start=inv_{agency.invite_token}"


async def create_agency_from_onboarding(
    session, request, *, bot_token: Optional[str] = None, trial_days: int = 0,
    operator: str = "operator",
):
    """ТЗ 5.2: agency + owner + first city (+ own bot) from a paid request.

    Returns (agency, invite_link). The owner is the person who filled the request;
    managers join through the link. Raises OnboardingError for anything the
    operator must decide on (city taken meanwhile, owner already in an agency).
    """
    from app.models.agency import Agency  # noqa: PLC0415
    from app.models.billing import BillingEvent, SubscriptionPlan  # noqa: PLC0415
    from app.models.manager import Manager  # noqa: PLC0415

    if request.status == "completed":
        raise OnboardingError("Заявка уже выполнена")
    check = await check_city_availability(session, request.city_name)
    if not check.available:
        raise OnboardingError(check.reason)
    taken_by = await session.scalar(select(Manager.agency_id).where(
        Manager.telegram_id == request.telegram_id))
    if taken_by is not None:
        raise OnboardingError("Этот Telegram уже состоит в другом агентстве")
    plan = await session.get(SubscriptionPlan, request.plan_id)
    if plan is None:
        raise OnboardingError(f"Нет тарифа {request.plan_id}")

    now = datetime.now(timezone.utc)
    if trial_days > 0:
        expires = now + timedelta(days=trial_days)
    elif plan.monthly_price > 0:
        expires = now + MONTH  # the first month comes with the connection fee
    else:
        expires = None  # one-off plan: nothing to renew
    token = secrets.token_hex(12)
    agency = Agency(
        name=request.agency_name, base_city=request.city_name, subscription_plan=plan.id,
        subscription_active=True, subscription_started_at=now, subscription_expires_at=expires,
        one_time_price_rub=plan.one_time_price, monthly_price_rub=plan.monthly_price,
        max_managers=plan.max_managers, max_cities=plan.max_cities,
        monthly_ai_budget_rub=plan.monthly_ai_budget,
        invite_token=token, onboarding_code=token, onboarding_completed_at=now,
        owner_telegram_id=request.telegram_id, is_active=True,
    )
    agency.owner_phone = request.phone
    session.add(agency)
    await session.flush()
    session.add(Manager(agency_id=agency.id, name=request.display_name or request.username or "Владелец",
                        telegram_id=request.telegram_id, preferred_platform="telegram",
                        role="owner", is_active=True))
    if request.payment_id:
        # Paid through ЮKassa: the payment was recorded when it arrived; only
        # tie it to the agency now, so revenue is not counted twice.
        await session.execute(update(BillingEvent).where(
            BillingEvent.payment_id == request.payment_id).values(agency_id=agency.id))
    else:
        session.add(BillingEvent(
            agency_id=agency.id, onboarding_request_id=request.id,
            event_type="trial_start" if trial_days > 0 else "payment",
            amount_rub=0 if trial_days > 0 else plan.one_time_price,
            payment_method="manual", expires_at_after=expires, created_by=operator,
            note=f"Подключение по заявке {str(request.id)[:8]}",
        ))
    request.status = "completed"
    request.agency_id = agency.id
    await session.commit()

    from app.routers.geo import CreateGeoRequest, _create_geo  # noqa: PLC0415

    await _create_geo(session, agency.id, CreateGeoRequest(city_name=request.city_name, region=""))
    username = None
    if bot_token:
        from app.services.agency_bots import attach_bot  # noqa: PLC0415

        username = await attach_bot(session, agency, bot_token)
    logger.info("Agency created from onboarding", agency_id=str(agency.id),
                plan=plan.id, city=request.city_name)
    return agency, invite_link(agency, username)


async def extend_subscription(session, agency, months: int, *, amount_rub: int = 0,
                              method: str = "manual", payment_id: Optional[str] = None,
                              created_by: str = "operator", note: Optional[str] = None):
    """Add N months from the later of today and the current expiry, and reactivate."""
    from app.models.billing import BillingEvent  # noqa: PLC0415

    if months < 1 or months > 36:
        raise OnboardingError("Продлить можно на 1–36 месяцев")
    now = datetime.now(timezone.utc)
    base = max(agency.subscription_expires_at or now, now)
    agency.subscription_expires_at = base + MONTH * months
    agency.subscription_active = True
    session.add(BillingEvent(
        agency_id=agency.id, event_type="subscription_renewed" if payment_id else "manually_extended",
        amount_rub=amount_rub, payment_method=method, payment_id=payment_id, months_added=months,
        expires_at_after=agency.subscription_expires_at, created_by=created_by, note=note,
    ))
    await session.commit()
    return agency


async def find_request(session, prefix: str, statuses: tuple[str, ...]):
    """A request by the first characters of its id, as the operator types it."""
    from app.models.billing import OnboardingRequest  # noqa: PLC0415

    prefix = (prefix or "").strip().lower()
    if len(prefix) < 6 or not re.fullmatch(r"[0-9a-f-]+", prefix):
        return None
    rows = (await session.execute(select(OnboardingRequest).where(
        func.cast(OnboardingRequest.id, Text).startswith(prefix),
        OnboardingRequest.status.in_(statuses),
    ))).scalars().all()
    return rows[0] if len(rows) == 1 else None


async def find_agency(session, prefix: str):
    from app.models.agency import Agency  # noqa: PLC0415

    prefix = (prefix or "").strip().lower()
    if len(prefix) < 6 or not re.fullmatch(r"[0-9a-f-]+", prefix):
        return None
    rows = (await session.execute(select(Agency).where(
        func.cast(Agency.id, Text).startswith(prefix)))).scalars().all()
    return rows[0] if len(rows) == 1 else None
