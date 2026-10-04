"""Operator-side billing actions and the daily subscription check. ТЗ «SaaS-слой» 6-7."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import structlog

from app.config import config

logger = structlog.get_logger()


async def set_suspended(session, agency, suspended: bool, by: str, note: Optional[str] = None):
    """Block or unblock an agency by hand. Recorded, so the history explains it."""
    from app.models.billing import BillingEvent  # noqa: PLC0415

    agency.subscription_active = not suspended
    agency.platform_notes = (f"Приостановлено: {note}" if note else "Приостановлено оператором") \
        if suspended else None
    session.add(BillingEvent(agency_id=agency.id, event_type="suspended" if suspended else "unsuspended",
                             created_by=by, note=note))
    await session.commit()
    logger.info("Agency suspension changed", agency_id=str(agency.id), suspended=suspended, by=by)
    return agency


def _days_word(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "день"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "дня"
    return "дней"


async def _tell_owners(session, agency, text: str) -> int:
    """To every active owner, through the agency's own bot if it has one."""
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.manager import Manager  # noqa: PLC0415
    from app.services.bot_abstraction import bot_layer  # noqa: PLC0415

    owners = (await session.execute(select(Manager.id).where(
        Manager.agency_id == agency.id, Manager.role == "owner", Manager.is_active.is_(True)
    ))).scalars().all()
    sent = 0
    for owner_id in owners:
        sent += bool(await bot_layer.notify_manager(str(owner_id), text))
    return sent


async def check_subscriptions(now: Optional[datetime] = None) -> dict:
    """ТЗ 7.1, daily: remind owners 7/3/1 days ahead, suspend after the grace period.

    A reminder goes out on the exact day (days left in PLATFORM_REMINDER_DAYS_BEFORE),
    so one daily run sends each one once. Suspension is recorded as an event and
    reported to the operators.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.database import async_session  # noqa: PLC0415
    from app.models.agency import Agency  # noqa: PLC0415
    from app.models.billing import BillingEvent  # noqa: PLC0415
    from app.services.billing import SubscriptionStatus, get_subscription_status  # noqa: PLC0415

    now = now or datetime.now(timezone.utc)
    stats = {"reminded": 0, "suspended": 0}
    suspended_names: list[str] = []
    async with async_session() as session:
        agencies = (await session.execute(select(Agency).where(
            Agency.is_active.is_(True), Agency.subscription_active.is_(True),
            Agency.subscription_expires_at.is_not(None),
        ))).scalars().all()
        for agency in agencies:
            days_left = (agency.subscription_expires_at.date() - now.date()).days
            if days_left in config.reminder_days:
                renew = (f"\nПродлить: {config.platform_landing_url.rstrip('/')}/renew"
                         if config.platform_landing_url else "\nДля продления напишите нам.")
                text = (f"Подписка REIP агентства «{agency.name}» закончится через {days_left} "
                        f"{_days_word(days_left)} — {agency.subscription_expires_at:%d.%m.%Y}.{renew}")
                if await _tell_owners(session, agency, text):
                    stats["reminded"] += 1
            if get_subscription_status(agency, now) == SubscriptionStatus.EXPIRED:
                agency.subscription_active = False
                session.add(BillingEvent(agency_id=agency.id, event_type="subscription_expired",
                                         created_by="system", note="Льготный период истёк"))
                stats["suspended"] += 1
                suspended_names.append(f"{agency.name} ({agency.base_city}), id {str(agency.id)[:8]}")
        await session.commit()

    if suspended_names:
        from app.services.sales_bot import notify_operators  # noqa: PLC0415

        await notify_operators("Приостановлены после льготного периода:\n" + "\n".join(suspended_names)
                               + "\n\nПродлить: /extend_<id> <месяцы>")
    logger.info("Subscriptions checked", **stats)
    return stats
