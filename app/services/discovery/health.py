"""Are the sources we collect from still alive? ТЗ «Сигналы» 2 и 5.

Every hour each active or sandbox source is read (its last few posts):

    readable, posted within QUIET_AFTER  -> healthy, failures reset
    readable, silent longer              -> degraded (still collected)
    unreadable                           -> dead, consecutive_failures + 1
    3 failures in a row                  -> status = disabled, owners told

"Could not check" is not "dead": a platform we cannot reach this hour (the
Telegram account is busy, no VK token, out of budget) leaves its sources as they
were. And when every source of a platform fails in the same hour, that is the
platform down, not all of its chats deleted at once -- nobody is counted then.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import select

from app.services.discovery.probes import fetch_posts, source_ref
from app.services.discovery.rate_limit_guard import RateLimitGuard
from app.services.discovery.types import FORUM, RSS, TELEGRAM, VK, YOUTUBE

logger = structlog.get_logger()

FAILURES_TO_DISABLE = 3
POSTS_TO_READ = 5
QUIET_AFTER = {TELEGRAM: timedelta(days=14), VK: timedelta(days=14),
               YOUTUBE: timedelta(days=90), RSS: timedelta(days=30), FORUM: timedelta(days=30)}
READ_COST = {TELEGRAM: 1, VK: 1, YOUTUBE: 2, RSS: 1}


@dataclass
class HealthResult:
    status: str  # healthy | degraded | dead | skipped
    last_post_at: Optional[datetime] = None
    reason: str = ""


class SourceHealthChecker:
    def __init__(self, clients, guard=None, now=None):
        self.clients = clients
        self.guard = guard or RateLimitGuard()
        self._now = now or (lambda: datetime.now(timezone.utc))

    async def _platform_ready(self, platform: str) -> bool:
        if platform == TELEGRAM:
            return await self.clients.telegram() is not None
        if platform == VK:
            return self.clients.vk() is not None
        if platform == YOUTUBE:
            return self.clients.youtube() is not None
        return platform == RSS

    async def check(self, source) -> HealthResult:
        platform, ref = source_ref(source)
        if not platform or not ref:
            return HealthResult("skipped", reason="неизвестный тип источника")
        if not await self._platform_ready(platform):
            return HealthResult("skipped", reason="площадка сейчас недоступна")
        if not await self.guard.spend(platform, READ_COST.get(platform, 1)):
            return HealthResult("skipped", reason="лимит площадки")
        posts = await fetch_posts(self.clients, platform, ref, POSTS_TO_READ)
        if posts is None:
            return HealthResult("dead", reason="не удалось прочитать")
        dated = [p.at for p in posts if p.at]
        last = max(dated) if dated else None
        if not posts or (last and self._now() - last > QUIET_AFTER.get(platform, timedelta(days=30))):
            return HealthResult("degraded", last, "давно нет публикаций")
        return HealthResult("healthy", last)


def apply_result(source, result: HealthResult, now: datetime) -> bool:
    """Write the check onto the source. True when it was just disabled."""
    if result.status == "skipped":
        return False
    source.last_health_check = now
    if result.last_post_at:
        source.last_post_at = result.last_post_at
    if result.status == "dead":
        source.health_status = "dead"
        source.consecutive_failures = (source.consecutive_failures or 0) + 1
        if source.consecutive_failures >= FAILURES_TO_DISABLE and source.status != "disabled":
            source.status = "disabled"
            return True
        return False
    source.health_status = result.status
    source.consecutive_failures = 0
    return False


async def _notify_owners(session, agency_id, sources) -> None:
    from app.models.manager import Manager  # noqa: PLC0415
    from app.services.bot_abstraction import bot_layer  # noqa: PLC0415

    names = "\n".join(f"• {s.source_name or s.source_url}" for s in sources[:10])
    more = f"\n…и ещё {len(sources) - 10}" if len(sources) > 10 else ""
    text = (f"Источники отключены — {FAILURES_TO_DISABLE} проверки подряд их не удалось "
            f"прочитать (удалены, закрыты или переименованы):\n{names}{more}\n\n"
            "Автопоиск ищет замену сам. Включить обратно можно в разделе «Источники».")
    owners = (await session.execute(select(Manager).where(
        Manager.agency_id == agency_id, Manager.role == "owner",
        Manager.is_active.is_(True)))).scalars().all()
    for owner in owners:
        try:
            await bot_layer.notify_manager(str(owner.id), text)
        except Exception as e:  # noqa: BLE001
            logger.warning("Source-disabled notice not sent", error=str(e)[:120])


async def check_sources(session, sources, clients, guard=None, now=None) -> dict:
    """Check ``sources`` and write the results. Returns counts per outcome."""
    now = now or datetime.now(timezone.utc)
    checker = SourceHealthChecker(clients, guard, now=lambda: now)
    results = []
    for source in sources:
        try:
            results.append((source, await checker.check(source)))
        except Exception as e:  # noqa: BLE001 - one source, not the run
            logger.warning("Health check failed", source_id=str(source.id), error=str(e)[:160])

    by_platform: dict[str, list[str]] = {}
    for source, result in results:
        by_platform.setdefault(source_ref(source)[0] or "?", []).append(result.status)
    outage = {p for p, st in by_platform.items()
              if len(st) >= 3 and all(s == "dead" for s in st)}
    if outage:
        logger.warning("Health check: platform looks down, nobody counted", platforms=sorted(outage))

    counts: dict[str, int] = {}
    disabled: dict = {}
    for source, result in results:
        if source_ref(source)[0] in outage:
            result = HealthResult("skipped", reason="площадка недоступна целиком")
        counts[result.status] = counts.get(result.status, 0) + 1
        if apply_result(source, result, now):
            disabled.setdefault(source.agency_id, []).append(source)
    await session.commit()
    for agency_id, items in disabled.items():
        counts["disabled"] = counts.get("disabled", 0) + len(items)
        await _notify_owners(session, agency_id, items)
    return counts


async def recheck_source(session, source) -> HealthResult:
    """One source, now (the owner's «Проверить»)."""
    from app.services.discovery.clients import PlatformClients  # noqa: PLC0415

    async with PlatformClients(telegram_wait_seconds=20) as clients:
        result = await SourceHealthChecker(clients).check(source)
    apply_result(source, result, datetime.now(timezone.utc))
    await session.commit()
    return result
