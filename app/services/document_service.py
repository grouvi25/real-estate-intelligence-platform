"""Document rendering (commercial offers, object reports). TZ section 32.

HTML is rendered with Jinja2 (always available). PDF conversion uses WeasyPrint,
which is an optional dependency because it needs system libraries (Pango/Cairo);
render_pdf lazily imports it and raises a clear 501 if it isn't installed, so the
HTML path keeps working everywhere (including CI).
"""
from __future__ import annotations

from typing import Any

import structlog
from jinja2 import Environment, select_autoescape

from app.exceptions import AppException

logger = structlog.get_logger()

_env = Environment(autoescape=select_autoescape(["html", "xml"]))


def _fmt_money(value: Any) -> str:
    try:
        return f"{int(value):,} ₽".replace(",", " ")
    except (TypeError, ValueError):
        return "—"


_env.filters["money"] = _fmt_money

# --- Templates -------------------------------------------------------------

COMMERCIAL_OFFER_TMPL = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<title>Подборка недвижимости</title>
<style>
 body { font-family: 'DejaVu Sans', Arial, sans-serif; color:#1a1a1a; margin:40px; }
 h1 { color:#0a5; } .agency { color:#666; margin-bottom:24px; }
 .prop { border:1px solid #ddd; border-radius:8px; padding:16px; margin:12px 0; }
 .price { font-size:20px; font-weight:bold; color:#0a5; }
 .score { float:right; background:#0a5; color:#fff; border-radius:12px; padding:2px 10px; }
 .pitch { color:#333; margin-top:8px; }
</style></head><body>
<h1>Персональная подборка</h1>
<div class="agency">{{ agency_name }}{% if manager_name %} · {{ manager_name }}{% endif %}</div>
{% if client_name %}<p>Для: <b>{{ client_name }}</b></p>{% endif %}
{% for p in properties %}
 <div class="prop">
  <span class="score">{{ p.match_score }}%</span>
  <div><b>{{ p.title }}</b></div>
  <div class="price">{{ p.price|money }}</div>
  {% if p.pitch %}<div class="pitch">{{ p.pitch }}</div>{% endif %}
 </div>
{% endfor %}
<p style="color:#999;font-size:12px;margin-top:32px">
 Документ сформирован автоматически. Не является публичной офертой.</p>
</body></html>"""

OBJECT_REPORT_TMPL = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<title>{{ title }}</title>
<style>
 body { font-family:'DejaVu Sans', Arial, sans-serif; margin:40px; color:#1a1a1a; }
 h1 { color:#0a5; } table { border-collapse:collapse; width:100%; margin-top:16px; }
 td,th { border:1px solid #ddd; padding:8px; text-align:left; }
 th { background:#f4f4f4; width:220px; }
</style></head><body>
<h1>{{ title }}</h1>
<table>
 <tr><th>Цена</th><td>{{ price|money }}</td></tr>
 <tr><th>Адрес</th><td>{{ address or '—' }}</td></tr>
 <tr><th>Район</th><td>{{ district or '—' }}</td></tr>
 <tr><th>Комнат</th><td>{{ rooms or '—' }}</td></tr>
 <tr><th>Площадь</th><td>{{ area_total or '—' }} м²</td></tr>
 <tr><th>Этаж</th><td>{{ floor or '—' }}{% if floors_total %} из {{ floors_total }}{% endif %}</td></tr>
</table>
{% if description %}<p>{{ description }}</p>{% endif %}
</body></html>"""

TEMPLATES = {
    "commercial_offer": COMMERCIAL_OFFER_TMPL,
    "object_report": OBJECT_REPORT_TMPL,
}


def render_html(doc_type: str, context: dict) -> str:
    """Render a document to an HTML string."""
    tmpl_src = TEMPLATES.get(doc_type)
    if tmpl_src is None:
        raise AppException(status_code=400, detail=f"Неизвестный тип документа: {doc_type}",
                           code="UNKNOWN_DOCUMENT_TYPE")
    return _env.from_string(tmpl_src).render(**context)


def render_pdf(doc_type: str, context: dict) -> bytes:
    """Render a document to PDF bytes (requires the optional 'pdf' extra)."""
    html = render_html(doc_type, context)
    try:
        from weasyprint import HTML  # noqa: PLC0415
    except Exception as e:  # noqa: BLE001 - ImportError or missing system libs
        logger.warning("WeasyPrint unavailable", error=str(e))
        raise AppException(
            status_code=501,
            detail="Генерация PDF недоступна на сервере (установите зависимость 'pdf')",
            code="PDF_UNAVAILABLE",
        ) from e
    return HTML(string=html).write_pdf()
