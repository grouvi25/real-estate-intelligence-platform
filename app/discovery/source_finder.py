"""Source Discovery: find + AI-evaluate monitoring sources. TZ section 15.2.

search_telegram_sources is the integration point for the Telethon userbot (added
with the collectors). Until then it returns no candidates. evaluate_and_save_sources
scores candidates via AI and persists them as active/sandbox sources.
"""
from __future__ import annotations

import uuid
from typing import Any

import structlog

logger = structlog.get_logger()

ACTIVE_THRESHOLD = 70
SANDBOX_THRESHOLD = 40


async def search_telegram_sources(geo_keywords: dict[str, Any]) -> list[dict]:
    """Find candidate Telegram sources for a geo.

    MVP: real search requires a Telethon userbot session (collectors module, added
    later). Returns [] for now; this is the stable integration point.
    """
    return []


async def evaluate_and_save_sources(
    session, candidates: list[dict], geo_id: uuid.UUID, geo_profile: dict[str, Any]
) -> int:
    """AI-evaluate candidates and persist relevant ones. Returns count saved."""
    from app.models.source import Source
    from app.prompts.source_evaluation import (
        SYSTEM_PROMPT_TELEGRAM_SOURCE_EVAL,
        USER_PROMPT_TELEGRAM_EVAL,
    )
    from app.services.ai_service import AIService, safe_ai_parse

    ai = AIService()
    saved = 0
    try:
        for cand in candidates:
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
            score = int(data.get("relevance_score", 0) or 0)
            if score < SANDBOX_THRESHOLD:
                continue

            status = "active" if score >= ACTIVE_THRESHOLD else "sandbox"
            username = cand.get("username", "")
            session.add(
                Source(
                    agency_id=geo_profile["agency_id"],
                    geo_location_id=geo_id,
                    source_type="telegram_chat",
                    source_url=cand.get("url") or f"https://t.me/{username}",
                    source_name=cand.get("name"),
                    external_id=cand.get("id"),
                    status=status,
                    score=score,
                    auto_found=True,
                )
            )
            saved += 1
        await session.commit()
    finally:
        await ai.close()

    logger.info("Source discovery evaluated", geo_id=str(geo_id), saved=saved, candidates=len(candidates))
    return saved
