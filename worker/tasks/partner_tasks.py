"""Partner Celery tasks. TZ section 20.2 (check_referral_expiry)."""
from __future__ import annotations

from datetime import datetime, timezone

import structlog
from celery import shared_task

from worker.async_runner import run_async

logger = structlog.get_logger()


async def _check_referral_expiry() -> int:
    """Mark pending referrals past their expiry as expired; notify managers."""
    from sqlalchemy import select

    from app.database import async_session
    from app.models.partner_referral import PartnerReferral
    from app.services.bot_abstraction import bot_layer

    now = datetime.now(timezone.utc)
    async with async_session() as session:
        stmt = select(PartnerReferral).where(
            PartnerReferral.status == "pending", PartnerReferral.expires_at < now
        )
        expired = (await session.execute(stmt)).scalars().all()
        for ref in expired:
            ref.status = "expired"
            ref.status_updated_at = now
        await session.commit()

        for ref in expired:
            if ref.referred_by_manager_id:
                await bot_layer.notify_manager(
                    str(ref.referred_by_manager_id),
                    f"⚠️ Партнёр не подтвердил лид #{str(ref.lead_id)[:8]} вовремя. Реферал закрыт.",
                )

    logger.info("Referral expiry check finished", expired=len(expired))
    return len(expired)


@shared_task(name="worker.tasks.partner_tasks.check_referral_expiry")
def check_referral_expiry() -> int:
    return run_async(_check_referral_expiry())
