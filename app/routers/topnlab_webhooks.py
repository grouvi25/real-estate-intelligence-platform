"""What TopNLab calls on REIP. ТЗ «Интеграция с TopNLab» v1.0, раздел 5.

- POST /api/topnlab/report-webhook — a TopNLab user pressed «Аналитика REIP» on
  selected orders; answer {"url": ...} within 10 seconds.
- GET  /api/topnlab/report-files/{name} — the file behind that url.
- POST /api/topnlab/incoming-webhook — card created/edited events (основной API,
  раздел 1). Logged only, until there is something to do with them.

TopNLab signs nothing. The report address carries a random per-agency token,
put there when the button is registered; it both identifies the agency and
keeps strangers from pulling its leads. The user's e-mail in the payload is not
used for that: REIP stores manager e-mails encrypted, and anyone can type one.

Every answer here carries ``Access-Control-Allow-Origin: *`` -- TopNLab's docs
say the download silently fails in the user's browser without it -- and the
preflight is answered before the app-wide CORS policy, which only admits
REIP's own origin, gets to refuse it.
"""
from __future__ import annotations

import io
import re
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import parse_qs

import structlog
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.config import config
from app.database import async_session

logger = structlog.get_logger()
router = APIRouter()

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
}
PUBLIC_PREFIXES = (
    "/api/topnlab/report-webhook",
    "/api/topnlab/report-files/",
    "/api/topnlab/incoming-webhook",
)
REPORT_PREFIX = "topnlab_reports/"
REPORT_NAME = re.compile(r"^[0-9a-f]{32}\.(xlsx|pdf)$")
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PDF_TYPE = "application/pdf"
CONTENT_TYPES = {"xlsx": XLSX_TYPE, "pdf": PDF_TYPE}
# TopNLab waits 10 s for the answer; a PDF that is not ready by then is sent as
# Excel instead -- a report in the other format beats no report.
PDF_BUDGET_SECONDS = 6.0
MAX_IDS = 1000


async def topnlab_cors(request: Request, call_next):
    """HTTP middleware for the public TopNLab paths only (see module docstring)."""
    path = request.url.path
    if not path.startswith(PUBLIC_PREFIXES):
        return await call_next(request)
    if request.method == "OPTIONS":
        return Response(status_code=200, headers=CORS_HEADERS)
    response = await call_next(request)
    # The app-wide middleware may add Allow-Credentials; with "*" as the origin
    # a browser would then reject the answer outright.
    if "access-control-allow-credentials" in response.headers:
        del response.headers["access-control-allow-credentials"]
    for key, value in CORS_HEADERS.items():
        response.headers[key] = value
    return response


def _json(content: Any, status_code: int = 200) -> JSONResponse:
    return JSONResponse(content=content, status_code=status_code, headers=CORS_HEADERS)


async def _config_by_token(session, token: Optional[str]):
    from app.models.agency_crm_config import AgencyCRMConfig  # noqa: PLC0415

    if not token or len(token) < 16:
        return None
    rows = (await session.execute(
        select(AgencyCRMConfig).where(
            AgencyCRMConfig.connector_type == "topnlab",
            AgencyCRMConfig.config["report_token"].astext == token,
        )
    )).scalars().all()
    # Compare again in constant time: the SQL match is only the lookup.
    for row in rows:
        if secrets.compare_digest(str((row.config or {}).get("report_token", "")), token):
            return row
    return None


def _ids(raw: Any) -> list[int]:
    if not isinstance(raw, list):
        return []
    out: list[int] = []
    for value in raw[:MAX_IDS]:
        text = str(value).strip()
        if text.isdigit():
            out.append(int(text))
    return out


async def _report_rows(session, agency_id: uuid.UUID, ids: list[int]) -> list[list[Any]]:
    from app.models.lead import Lead  # noqa: PLC0415
    from app.models.signal import Signal  # noqa: PLC0415
    from app.services.topnlab_adapter import SEGMENT_RU, URGENCY_RU  # noqa: PLC0415

    if not ids:
        return []
    leads = (await session.execute(
        select(Lead).where(Lead.agency_id == agency_id, Lead.topnlab_client_id.in_(ids))
        .order_by(Lead.created_at.desc())
    )).scalars().all()
    signal_ids = [lead.source_signal_id or lead.signal_id for lead in leads]
    signals = {}
    wanted = [sid for sid in signal_ids if sid]
    if wanted:
        for sig in (await session.execute(select(Signal).where(Signal.id.in_(wanted)))).scalars():
            signals[sig.id] = sig

    rows = []
    for lead in leads:
        sig = signals.get(lead.source_signal_id or lead.signal_id)
        source = sig.source.source_name if sig is not None and sig.source is not None else None
        rows.append([
            lead.topnlab_client_id,
            lead.created_at.astimezone(timezone.utc).strftime("%d.%m.%Y %H:%M") if lead.created_at else "",
            lead.intent_score,
            SEGMENT_RU.get(lead.segment, lead.segment or ""),
            URGENCY_RU.get(lead.urgency, lead.urgency or ""),
            lead.budget_min,
            lead.budget_max,
            lead.status,
            lead.name or "",
            f"@{lead.telegram_username}" if lead.telegram_username else "",
            source or lead.source_type,
            (sig.signal_url or "") if sig is not None else "",
            " ".join((sig.raw_text or "").split())[:1000] if sig is not None else "",
        ])
    return rows


HEADERS = ["Заявка TopNLab", "Лид создан (UTC)", "Score", "Сегмент", "Срочность",
           "Бюджет от, ₽", "Бюджет до, ₽", "Статус в REIP", "Имя", "Telegram",
           "Источник", "Ссылка на сообщение", "Сообщение"]


def build_report_pdf(rows: list[list[Any]], requested: int) -> bytes:
    """The same table as a PDF (A4 landscape) -- the format the ТЗ names.
    WeasyPrint is in the image for documents (Dockerfile, DejaVu for Cyrillic)."""
    from html import escape  # noqa: PLC0415

    from weasyprint import HTML  # noqa: PLC0415

    def cell(value: Any, idx: int) -> str:
        if value is None:
            return ""
        if idx in (5, 6) and isinstance(value, (int, float)):
            return f"{int(value):,}".replace(",", "\u00a0")
        text = str(value)
        if idx == 12 and len(text) > 400:
            text = text[:400] + "…"
        if idx == 11 and text.startswith("http"):
            return f'<a href="{escape(text)}">ссылка</a>'
        return escape(text)

    stamp = datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
    head = "".join(f"<th>{escape(h)}</th>" for h in HEADERS)
    body = "".join("<tr>" + "".join(f"<td>{cell(v, i)}</td>" for i, v in enumerate(r)) + "</tr>"
                   for r in rows)
    if not rows:
        body = f'<tr><td colspan="{len(HEADERS)}">Среди выбранных заявок ({requested}) нет пришедших из REIP.</td></tr>'
    html = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><style>
      @page {{ size: A4 landscape; margin: 12mm; }}
      body {{ font-family: "DejaVu Sans", sans-serif; font-size: 7.5pt; color: #111; }}
      h1 {{ font-size: 13pt; margin: 0 0 2mm; }}
      .meta {{ color: #555; margin-bottom: 4mm; }}
      table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
      th {{ background: #f0f0f0; text-align: left; }}
      th, td {{ border: 0.5pt solid #bbb; padding: 1.2mm; vertical-align: top;
               overflow-wrap: anywhere; }}
      th:nth-child(13), td:nth-child(13) {{ width: 30%; }}
      tr {{ page-break-inside: avoid; }}
    </style></head><body>
      <h1>Аналитика REIP — лиды</h1>
      <div class="meta">Выбрано заявок: {requested}, из REIP: {len(rows)}. Сформировано {stamp}.</div>
      <table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>
    </body></html>"""
    return HTML(string=html).write_pdf()


def build_report_xlsx(rows: list[list[Any]], requested: int) -> bytes:
    """One sheet, one row per lead. Built in milliseconds with no system
    libraries; also the fallback when a PDF does not fit TopNLab's 10 seconds."""
    from openpyxl import Workbook  # noqa: PLC0415
    from openpyxl.styles import Font  # noqa: PLC0415

    wb = Workbook()
    ws = wb.active
    ws.title = "Лиды REIP"
    ws.append(HEADERS)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for row in rows:
        ws.append(row)
    if not rows:
        ws.append([f"Среди выбранных заявок ({requested}) нет пришедших из REIP."])
    widths = [14, 17, 7, 16, 11, 13, 13, 13, 22, 18, 26, 40, 80]
    for idx, width in enumerate(widths, start=1):
        ws.column_dimensions[ws.cell(row=1, column=idx).column_letter].width = width
    ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def build_report(rows: list[list[Any]], requested: int, fmt: str) -> tuple[bytes, str]:
    """(file, extension). PDF unless Excel was asked for, or the PDF did not
    make it within PDF_BUDGET_SECONDS, or WeasyPrint is not available."""
    import asyncio  # noqa: PLC0415

    if fmt != "xlsx":
        try:
            data = await asyncio.wait_for(
                asyncio.to_thread(build_report_pdf, rows, requested), PDF_BUDGET_SECONDS)
            return data, "pdf"
        except Exception as e:  # noqa: BLE001 - timeout, missing libs: Excel instead
            logger.warning("TopNLab PDF report fell back to Excel", rows=len(rows),
                           error=f"{type(e).__name__}: {str(e)[:120]}")
    return build_report_xlsx(rows, requested), "xlsx"


@router.post("/report-webhook")
async def report_webhook(request: Request, token: Optional[str] = None,
                         format: Optional[str] = None):  # noqa: A002 - the ТЗ's query name
    """ТЗ 5.1: build the «Лиды REIP» report for the orders a TopNLab user chose.
    ``?format=xlsx`` gives Excel (the second button); otherwise PDF."""
    from app.services.storage import get_storage  # noqa: PLC0415

    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    if not isinstance(body, dict):
        body = {}

    async with async_session() as session:
        cfg = await _config_by_token(session, token)
        if cfg is None:
            logger.warning("TopNLab report webhook: unknown token")
            return _json({"error": "Агентство не найдено"}, status_code=404)
        ids = _ids(body.get("ids"))
        rows = await _report_rows(session, cfg.agency_id, ids)

    data, ext = await build_report(rows, len(ids), (format or "pdf").lower())
    name = f"{uuid.uuid4().hex}.{ext}"
    await get_storage().upload(REPORT_PREFIX + name, data, CONTENT_TYPES[ext])
    url = f"{config.base_url.rstrip('/')}/api/topnlab/report-files/{name}"
    logger.info("TopNLab report built", agency_id=str(cfg.agency_id),
                requested=len(ids), found=len(rows), report_id=body.get("report_id"))
    return _json({"url": url})


@router.get("/report-files/{name}")
async def report_file(name: str):
    """The report itself. The name is 128 random bits; nothing else guards it,
    exactly like the S3 link TopNLab's docs expect in its place."""
    from app.services.storage import get_storage  # noqa: PLC0415

    if not REPORT_NAME.match(name):
        return _json({"error": "Файл не найден"}, status_code=404)
    try:
        data = await get_storage().download(REPORT_PREFIX + name)
    except Exception:  # noqa: BLE001 - absent object: the same answer as a bad name
        return _json({"error": "Файл не найден"}, status_code=404)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ext = name.rsplit(".", 1)[-1]
    return Response(content=data, media_type=CONTENT_TYPES[ext], headers={
        **CORS_HEADERS,
        "Content-Disposition": f'attachment; filename="reip-leads-{stamp}.{ext}"',
        "Cache-Control": "private, max-age=3600",
    })


@router.post("/incoming-webhook")
async def incoming_webhook(request: Request, token: Optional[str] = None):
    """ТЗ 5.2: TopNLab → REIP events. Accepted and logged, not acted upon yet.

    TopNLab sends card events as form data (id, type, type_id, type_name), not
    JSON, so both are read.
    """
    async with async_session() as session:
        cfg = await _config_by_token(session, token)
    if cfg is None:
        return _json({"status": "error", "error": "forbidden"}, status_code=403)

    raw = await request.body()
    ctype = request.headers.get("content-type", "")
    event: dict[str, Any]
    if "json" in ctype:
        try:
            import json as _json_mod  # noqa: PLC0415

            parsed = _json_mod.loads(raw or b"{}")
            event = parsed if isinstance(parsed, dict) else {"body": parsed}
        except ValueError:
            event = {}
    else:
        event = {k: v[0] if len(v) == 1 else v
                 for k, v in parse_qs(raw.decode("utf-8", "replace")).items()}
    logger.info("TopNLab incoming webhook", agency_id=str(cfg.agency_id),
                entity_id=event.get("id"), entity_type=event.get("type"),
                keys=sorted(event.keys())[:20])
    return _json({"status": "ok", "received": True})
