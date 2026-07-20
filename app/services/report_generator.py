"""Daily manager report. TZ section 27.1.

build_daily_report aggregates the last 24h for an agency (pure SQL, testable);
format_report_text renders a concise Russian summary for Telegram. The Celery
task (worker/tasks/report_tasks.py) optionally enriches it with an AI narrative
and delivers it to the agency owner.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import func, select

from app.models.geo_location import GeoLocation
from app.models.lead import Lead
from app.models.signal import Signal
from app.models.source import Source

logger = structlog.get_logger()


async def build_daily_report(session, agency_id: uuid.UUID) -> dict:
    """Aggregate the last 24h of activity for one agency."""
    since = datetime.now(timezone.utc) - timedelta(hours=24)

    # Signals in the window.
    sig_total = await session.scalar(
        select(func.count()).select_from(Signal).where(
            Signal.agency_id == agency_id, Signal.created_at >= since)) or 0
    sig_hot = await session.scalar(
        select(func.count()).select_from(Signal).where(
            Signal.agency_id == agency_id, Signal.created_at >= since,
            Signal.urgency == "hot")) or 0
    sig_warm = await session.scalar(
        select(func.count()).select_from(Signal).where(
            Signal.agency_id == agency_id, Signal.created_at >= since,
            Signal.urgency == "warm")) or 0

    seg_rows = (await session.execute(
        select(Signal.segment, func.count()).where(
            Signal.agency_id == agency_id, Signal.created_at >= since,
            Signal.segment.isnot(None)).group_by(Signal.segment)
        .order_by(func.count().desc()))).all()
    top_segment = seg_rows[0][0] if seg_rows else None

    geo_rows = (await session.execute(
        select(GeoLocation.city_name, func.count())
        .select_from(Signal).join(GeoLocation, Signal.geo_location_id == GeoLocation.id)
        .where(Signal.agency_id == agency_id, Signal.created_at >= since)
        .group_by(GeoLocation.city_name).order_by(func.count().desc()))).all()
    top_geo = geo_rows[0][0] if geo_rows else None

    # Leads.
    new_leads = await session.scalar(
        select(func.count()).select_from(Lead).where(
            Lead.agency_id == agency_id, Lead.created_at >= since)) or 0
    no_contact = await session.scalar(
        select(func.count()).select_from(Lead).where(
            Lead.agency_id == agency_id, Lead.status == "new",
            Lead.created_at < since)) or 0

    # Sources.
    active_sources = await session.scalar(
        select(func.count()).select_from(Source).where(
            Source.agency_id == agency_id, Source.status == "active")) or 0
    sandbox_sources = await session.scalar(
        select(func.count()).select_from(Source).where(
            Source.agency_id == agency_id, Source.status == "sandbox")) or 0

    return {
        "signals": {"total": sig_total, "hot": sig_hot, "warm": sig_warm,
                    "top_segment": top_segment, "top_geo": top_geo,
                    "by_segment": {s: c for s, c in seg_rows},
                    "by_city": {c: n for c, n in geo_rows}},
        "leads": {"new": new_leads, "no_contact_over_24h": no_contact},
        "sources": {"active": active_sources, "sandbox": sandbox_sources},
    }


def format_report_text(agency_name: str, data: dict) -> str:
    """Render a compact HTML summary for Telegram."""
    s = data["signals"]
    lead = data["leads"]
    src = data["sources"]
    lines = [
        f"📊 <b>Сводка за сутки — {agency_name}</b>",
        "",
        f"🔔 Сигналы: {s['total']} (🔥 {s['hot']} · 🌤 {s['warm']})",
    ]
    if s.get("top_segment"):
        lines.append(f"   Топ-сегмент: {s['top_segment']}")
    if s.get("top_geo"):
        lines.append(f"   Топ-город: {s['top_geo']}")
    lines += [
        f"👤 Лиды: новых {lead['new']} · без контакта &gt;24ч: {lead['no_contact_over_24h']}",
        f"📡 Источники: активных {src['active']} · в sandbox {src['sandbox']}",
    ]
    if lead["no_contact_over_24h"] > 0:
        lines.append("")
        lines.append(f"⚠️ {lead['no_contact_over_24h']} лид(ов) ждут первого контакта!")
    return "\n".join(lines)
