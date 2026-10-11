"""SandboxTester: is the candidate worth collecting? ТЗ «Сигналы» 2.7.

Reads the last 20 posts, has the AI score them, checks the source is alive:

    ACTIVATE  score ≥ 70 and alive   -> sources.status = active
    SANDBOX   score 40-69 and alive  -> sources.status = sandbox, re-test in 7 days
    REJECT    score < 40 or not alive -> kept in discovery_candidates, no source

Scoring uses the source-evaluation prompt REIP already runs (ПОКУПАТЕЛИ, not
"any real-estate content" as the ТЗ prompt has it): on live data the broad
version let a long-term rental chat in at 80 and it produced 22 renter "signals".
Thresholds come from the agency's discovery settings.

"Alive" is measured per platform: the ТЗ's 48 hours for chats and groups; for
YouTube the ТЗ's own 90 days (nobody uploads daily); 14 days for news and forum
feeds.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import structlog

from app.services.discovery.probes import fetch_posts
from app.services.discovery.types import (
    FORUM,
    RSS,
    TELEGRAM,
    TG_CATALOG,
    VK,
    YOUTUBE,
    SandboxResult,
    SourceCandidate,
)

logger = structlog.get_logger()

SAMPLE_SIZE = 20
CONCURRENCY = 5
ALIVE_WITHIN = {TELEGRAM: timedelta(hours=48), TG_CATALOG: timedelta(hours=48),
                VK: timedelta(hours=48), YOUTUBE: timedelta(days=90),
                RSS: timedelta(days=14), FORUM: timedelta(days=14)}
# what reading SAMPLE_SIZE posts costs on the rate guard
READ_COST = {TELEGRAM: 1, TG_CATALOG: 1, VK: 3, YOUTUBE: 2, RSS: 1, FORUM: 1}
GUARD_PLATFORM = {TG_CATALOG: TELEGRAM, FORUM: FORUM}
RENTAL_SCORE_CAP = 15


def verdict_for(score: float, alive: bool, activate: int = 70, sandbox: int = 40) -> str:
    if not alive or score < sandbox:
        return "REJECT"
    return "ACTIVATE" if score >= activate else "SANDBOX"


def is_alive(platform: str, posts, now=None) -> bool:
    if not posts:
        return False
    now = now or datetime.now(timezone.utc)
    dated = [p.at for p in posts if p.at]
    if not dated:
        return True  # VK обсуждения carry no date; readable text is the best we know
    return now - max(dated) <= ALIVE_WITHIN.get(platform, timedelta(hours=48))


def candidate_ref(c: SourceCandidate) -> str:
    return c.url if c.platform in (RSS, FORUM) else c.external_id


class SandboxTester:
    def __init__(self, clients, guard, city: str, agency_id, activate: int = 70,
                 sandbox: int = 40, ai=None):
        self.clients = clients
        self.guard = guard
        self.city = city
        self.agency_id = agency_id
        self.activate = activate
        self.sandbox = sandbox
        self._ai = ai

    async def _score_sample(self, c: SourceCandidate, texts: list[str]) -> float:
        from app.prompts.source_evaluation import (  # noqa: PLC0415
            SYSTEM_PROMPT_TELEGRAM_SOURCE_EVAL,
            USER_PROMPT_TELEGRAM_EVAL,
        )
        from app.services.ai_service import safe_ai_parse  # noqa: PLC0415

        prompt = USER_PROMPT_TELEGRAM_EVAL.format(
            target_city=self.city, name=c.name, username=c.external_id,
            description=c.description[:500], members_count=c.audience,
            sample_messages="\n".join(f"- {t[:280]}" for t in texts[:SAMPLE_SIZE]))
        raw = await self._ai.complete(SYSTEM_PROMPT_TELEGRAM_SOURCE_EVAL, prompt,
                                      "source_evaluation", agency_id=str(self.agency_id))
        data = safe_ai_parse(raw, {"relevance_score": 0})
        try:
            value = float(data.get("relevance_score", 0) or 0)
        except (TypeError, ValueError):
            value = 0.0
        if data.get("is_rental_focused") is True:
            value = min(value, RENTAL_SCORE_CAP)
        return max(0.0, min(100.0, value))

    async def test_one(self, c: SourceCandidate) -> SandboxResult:
        platform = GUARD_PLATFORM.get(c.platform, c.platform)
        if not await self.guard.spend(platform, READ_COST.get(c.platform, 1)):
            return SandboxResult(c, 0.0, False, "REJECT", "лимит площадки исчерпан")
        posts = await fetch_posts(self.clients, c.platform, candidate_ref(c), SAMPLE_SIZE)
        if posts is None:
            return SandboxResult(c, 0.0, False, "REJECT", "источник не читается")
        alive = is_alive(c.platform, posts)
        dated = [p.at for p in posts if p.at]
        if dated:
            c.last_post_at = max(dated)
        texts = [p.text for p in posts if len(p.text or "") > 20] or c.samples
        if not texts:
            return SandboxResult(c, 0.0, alive, "REJECT", "нет текста для оценки")
        try:
            score = await self._score_sample(c, texts)
        except Exception as e:  # noqa: BLE001 - AI down: test again later, not reject
            logger.warning("Sandbox AI failed", candidate=c.key, error=str(e)[:120])
            return SandboxResult(c, 0.0, alive, "SANDBOX", "ИИ недоступен, повторим",
                                 retry_only=True)
        verdict = verdict_for(score, alive, self.activate, self.sandbox)
        reason = "" if alive else "давно нет публикаций"
        return SandboxResult(c, score, alive, verdict, reason)

    async def test_batch(self, candidates: list[SourceCandidate]) -> list[SandboxResult]:
        from app.services.ai_service import AIService  # noqa: PLC0415

        own_ai = self._ai is None
        if own_ai:
            self._ai = AIService()
        sem = asyncio.Semaphore(CONCURRENCY)

        async def one(c):
            async with sem:
                try:
                    return await self.test_one(c)
                except Exception as e:  # noqa: BLE001 - one bad candidate, not the run
                    logger.warning("Sandbox test failed", candidate=c.key, error=str(e)[:160])
                    return SandboxResult(c, 0.0, False, "REJECT", "ошибка проверки")

        try:
            return list(await asyncio.gather(*(one(c) for c in candidates)))
        finally:
            if own_ai:
                await self._ai.close()
                self._ai = None
