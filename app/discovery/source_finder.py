"""Source Discovery: find + AI-evaluate monitoring sources. TZ section 15.2.

search_telegram_sources is the integration point for the Telethon userbot (added
with the collectors). Until then it returns no candidates. evaluate_and_save_sources
scores candidates via AI and persists them as active/sandbox sources.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

import structlog
from sqlalchemy import select

logger = structlog.get_logger()

ACTIVE_THRESHOLD = 70
SANDBOX_THRESHOLD = 40
# Evaluations ran one after another, ~8 s each. With VK added the first live run
# over Геленджик had enough candidates to blow the worker's 300 s ceiling
# ("Async task exceeded timeout"), and because the whole thing committed once at
# the end, every source it had already judged was thrown away. Candidates are now
# scored a batch at a time and each batch is committed, so a run that is cut off
# still leaves behind everything it finished.
EVALUATION_BATCH = 5


async def search_telegram_sources(geo_keywords: dict[str, Any]) -> list[dict]:
    """Find candidate Telegram sources for a geo via the Telethon collector.

    Uses the ``search_queries.telegram`` vocabulary from the geo keyword set. If
    no Telethon session is configured the collector returns [] (stable no-op).
    """
    from app.collectors.telegram_collector import search_candidate_sources

    queries = (geo_keywords.get("search_queries") or {}).get("telegram") or []
    if not queries:
        queries = geo_keywords.get("city_variations") or []
    if not queries:
        return []
    return [
        {**c, "channel": "telegram"}
        for c in await search_candidate_sources(queries, limit=10)
    ]


async def search_vk_sources(geo_keywords: dict[str, Any]) -> list[dict]:
    """Find candidate VK groups for a geo.

    The keyword builder has always produced search_queries.vk_groups and nothing
    read them, so those queries were generated for no one. Without
    VK_SERVICE_TOKEN the collector returns [] (stable no-op), same as Telethon.
    """
    from app.collectors.vk_collector import search_candidate_groups

    queries = (geo_keywords.get("search_queries") or {}).get("vk_groups") or []
    if not queries:
        queries = geo_keywords.get("city_variations") or []
    if not queries:
        return []
    return [{**c, "channel": "vk"} for c in await search_candidate_groups(queries)]


async def evaluate_and_save_sources(
    session, candidates: list[dict], geo_id: uuid.UUID, geo_profile: dict[str, Any]
) -> int:
    """AI-evaluate candidates and persist relevant ones. Returns count saved."""
    from app.prompts.source_evaluation import (
        SYSTEM_PROMPT_TELEGRAM_SOURCE_EVAL,
        USER_PROMPT_TELEGRAM_EVAL,
    )
    from app.services.ai_service import AIService, safe_ai_parse

    ai = AIService()
    saved = 0

    async def score(cand: dict) -> int:
        prompt = USER_PROMPT_TELEGRAM_EVAL.format(
            target_city=geo_profile.get("city_name", ""),
            name=cand.get("name", ""),
            username=cand.get("username", ""),
            description=cand.get("description", ""),
            members_count=cand.get("members", 0),
            sample_messages="\n".join(cand.get("samples", [])[:3]),
        )
        res = await ai.complete(
            SYSTEM_PROMPT_TELEGRAM_SOURCE_EVAL,
            prompt,
            "source_evaluation",
            agency_id=str(geo_profile.get("agency_id", "global")),
        )
        data = safe_ai_parse(res, {"relevance_score": 0})
        return int(data.get("relevance_score", 0) or 0)

    try:
        for start in range(0, len(candidates), EVALUATION_BATCH):
            batch = candidates[start:start + EVALUATION_BATCH]
            scores = await asyncio.gather(*(score(c) for c in batch))
            for cand, score_value in zip(batch, scores):
                saved += await _persist(session, cand, score_value, geo_id, geo_profile)
            # Committing per batch is what makes an interrupted run useful.
            await session.commit()
    finally:
        await ai.close()

    logger.info("Source discovery evaluated", geo_id=str(geo_id), saved=saved,
                candidates=len(candidates))
    return saved


async def _persist(session, cand: dict, score: int, geo_id: uuid.UUID,
                   geo_profile: dict[str, Any]) -> int:
    """Store one evaluated candidate. Returns 1 if a new source was added."""
    from app.models.source import Source

    if score < SANDBOX_THRESHOLD:
        return 0

    status = "active" if score >= ACTIVE_THRESHOLD else "sandbox"
    username = cand.get("username", "")
    channel = cand.get("channel", "telegram")
    source_type = "vk_group" if channel == "vk" else "telegram_chat"
    default_url = (f"https://vk.com/{username}" if channel == "vk"
                   else f"https://t.me/{username}")
    url = cand.get("url") or default_url

    # Discovery runs weekly over the same city and re-finds the same chats, so
    # without this every run added another copy of each source -- and a source
    # the agency had paused came back as a fresh active row. Only the score is
    # refreshed; the status is the manager's.
    existing = (await session.execute(
        select(Source).where(
            Source.agency_id == geo_profile["agency_id"],
            Source.source_url == url,
        )
    )).scalars().first()
    if existing is not None:
        existing.score = score
        existing.source_name = cand.get("name") or existing.source_name
        return 0

    session.add(
        Source(
            agency_id=geo_profile["agency_id"],
            geo_location_id=geo_id,
            source_type=source_type,
            source_url=url,
            source_name=cand.get("name"),
            # Both collectors resolve a source by handle, not numeric id.
            external_id=username or cand.get("id"),
            status=status,
            score=score,
            auto_found=True,
        )
    )
    return 1
