"""Subscription gate and plan limits. ТЗ «SaaS-слой» v1, раздел 3.

A subscription is active while ``subscription_active`` holds and the expiry date,
if there is one, has not passed. After expiry the agency gets GRACE_PERIOD_DAYS
of read-only access, then it is blocked. No expiry date means lifetime -- that is
what agencies created before billing have, so switching this on changes nothing
for them.

The gate sits in get_current_manager rather than on a handful of routers as the
ТЗ lists them: a check added router by router is a check forgotten on the next
router. Collection stops for blocked agencies too -- otherwise a client who
stopped paying would keep costing the platform AI calls every five minutes.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.exceptions import AppException

GRACE_PERIOD_DAYS = 14


class SubscriptionStatus:
    ACTIVE = "active"
    GRACE = "grace"  # expired, reading still allowed
    EXPIRED = "expired"  # blocked


# Reachable even for a blocked agency: the cabinet has to be able to say why it
# is blocked and who the user is, or the owner is left with a blank screen.
ALWAYS_ALLOWED_PATHS = (
    "/api/auth/config",
    "/api/billing/status",
)

READ_METHODS = {"GET", "HEAD", "OPTIONS"}


def get_subscription_status(agency: Any, now: Optional[datetime] = None) -> str:
    if not getattr(agency, "subscription_active", True):
        return SubscriptionStatus.EXPIRED
    expires = getattr(agency, "subscription_expires_at", None)
    if expires is None:
        return SubscriptionStatus.ACTIVE
    now = now or datetime.now(timezone.utc)
    if expires > now:
        return SubscriptionStatus.ACTIVE
    if expires > now - timedelta(days=GRACE_PERIOD_DAYS):
        return SubscriptionStatus.GRACE
    return SubscriptionStatus.EXPIRED


def _renewal_hint() -> str:
    from app.config import config  # noqa: PLC0415

    url = getattr(config, "platform_landing_url", None)
    return f" Продлить: {url.rstrip('/')}/renew" if url else " Обратитесь к оператору платформы."


def require_active_subscription(agency: Any, *, write_operation: bool,
                                now: Optional[datetime] = None) -> None:
    """402 when the subscription does not allow this request."""
    status = get_subscription_status(agency, now)
    if status == SubscriptionStatus.ACTIVE:
        return
    if status == SubscriptionStatus.GRACE:
        if write_operation:
            raise AppException(
                status_code=402,
                detail=("Подписка истекла. Данные можно смотреть ещё до "
                        f"{_grace_end(agency):%d.%m.%Y}, изменения недоступны." + _renewal_hint()),
                code="SUBSCRIPTION_GRACE",
            )
        return
    raise AppException(
        status_code=402,
        detail="Подписка неактивна, кабинет заблокирован." + _renewal_hint(),
        code="SUBSCRIPTION_EXPIRED",
    )


def _grace_end(agency: Any) -> datetime:
    return agency.subscription_expires_at + timedelta(days=GRACE_PERIOD_DAYS)


def gate_request(agency: Any, method: str, path: str, now: Optional[datetime] = None) -> None:
    """The per-request form used by get_current_manager."""
    if any(path.startswith(p) for p in ALWAYS_ALLOWED_PATHS):
        return
    require_active_subscription(agency, write_operation=method.upper() not in READ_METHODS, now=now)


LIMIT_NAMES = {"managers": "менеджеров", "cities": "городов"}


def check_plan_limit(agency: Any, limit_name: str, current_count: int) -> None:
    """403 if adding one more would exceed the plan. A NULL limit is no limit."""
    limit = getattr(agency, f"max_{limit_name}", None)
    if limit is None or current_count < limit:
        return
    raise AppException(
        status_code=403,
        detail=(f"По тарифу доступно не больше {limit} {LIMIT_NAMES.get(limit_name, limit_name)}. "
                "Чтобы добавить ещё, смените тариф."),
        code=f"PLAN_LIMIT_{limit_name.upper()}",
    )


def collectable_agencies_clause(now: Optional[datetime] = None):
    """SQL condition on Agency: still worth collecting for (active or in grace)."""
    from sqlalchemy import or_  # noqa: PLC0415

    from app.models.agency import Agency  # noqa: PLC0415

    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=GRACE_PERIOD_DAYS)
    return (
        Agency.is_active.is_(True)
        & Agency.subscription_active.is_(True)
        & or_(Agency.subscription_expires_at.is_(None), Agency.subscription_expires_at > cutoff)
    )


def collectable_agency_ids(now: Optional[datetime] = None):
    """Subquery of agency ids whose sources are still collected."""
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.agency import Agency  # noqa: PLC0415

    return select(Agency.id).where(collectable_agencies_clause(now))


def status_payload(agency: Any, now: Optional[datetime] = None) -> dict:
    status = get_subscription_status(agency, now)
    expires = agency.subscription_expires_at
    return {
        "status": status,
        "plan": agency.subscription_plan,
        "expires_at": expires.isoformat() if expires else None,
        "grace_until": _grace_end(agency).isoformat() if expires else None,
        "limits": {"managers": agency.max_managers, "cities": agency.max_cities},
    }
