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

PRELIMINARY_CONTRACT_TMPL = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<title>Предварительный договор купли-продажи</title>
<style>
 body { font-family:'DejaVu Sans', Arial, sans-serif; margin:40px; color:#1a1a1a;
        font-size:13px; line-height:1.6; }
 h1 { font-size:18px; text-align:center; margin-bottom:4px; }
 .meta { text-align:center; color:#666; margin-bottom:24px; }
 .clause { margin:14px 0; } .clause b { display:block; margin-bottom:4px; }
 table { border-collapse:collapse; width:100%; margin:12px 0; }
 td,th { border:1px solid #ddd; padding:7px; text-align:left; }
 th { background:#f4f4f4; width:210px; }
 .sign { margin-top:40px; display:flex; justify-content:space-between; }
 .sign div { width:45%; border-top:1px solid #333; padding-top:6px; }
 .note { color:#999; font-size:11px; margin-top:28px; }
</style></head><body>
<h1>Предварительный договор купли-продажи недвижимости</h1>
<div class="meta">{{ city or 'г. ______' }} · {{ contract_date }}</div>

<div class="clause"><b>1. Стороны</b>
Продавец: {{ agency_name or '______' }}{% if manager_name %}, представитель {{ manager_name }}{% endif %}.<br>
Покупатель: {{ client_name or '______' }}{% if client_phone %}, тел. {{ client_phone }}{% endif %}.</div>

<div class="clause"><b>2. Предмет договора</b>
Стороны обязуются заключить основной договор купли-продажи следующего объекта:</div>
<table>
 <tr><th>Объект</th><td>{{ property_title }}</td></tr>
 <tr><th>Адрес</th><td>{{ address or '—' }}</td></tr>
 <tr><th>Площадь</th><td>{{ area_total or '—' }} м²</td></tr>
 <tr><th>Комнат</th><td>{{ rooms or '—' }}</td></tr>
 <tr><th>Этаж</th><td>{{ floor or '—' }}{% if floors_total %} из {{ floors_total }}{% endif %}</td></tr>
 <tr><th>Цена объекта</th><td><b>{{ price|money }}</b></td></tr>
</table>

<div class="clause"><b>3. Обеспечительный платёж</b>
Покупатель вносит {{ deposit_amount|money }} в течение {{ deposit_days }} дней с даты
подписания настоящего договора. Сумма засчитывается в счёт цены объекта.</div>

<div class="clause"><b>4. Срок заключения основного договора</b>
Основной договор подлежит заключению не позднее {{ final_date }}.</div>

<div class="clause"><b>5. Прочие условия</b>
Настоящий договор составлен в двух экземплярах, имеющих равную юридическую силу,
по одному для каждой из сторон.</div>

<div class="sign"><div>Продавец / представитель</div><div>Покупатель</div></div>
<p class="note">Документ сформирован автоматически системой REIP {{ contract_date }}.
Перед подписанием требует проверки юристом. Не является публичной офертой.</p>
</body></html>"""

CHECKLIST_TMPL = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<title>Чек-лист проверки документов</title>
<style>
 body { font-family:'DejaVu Sans', Arial, sans-serif; margin:40px; color:#1a1a1a; font-size:13px; }
 h1 { color:#0a5; font-size:19px; margin-bottom:2px; }
 .obj { color:#666; margin-bottom:20px; }
 h2 { font-size:14px; margin:22px 0 6px; border-bottom:1px solid #ddd; padding-bottom:4px; }
 ul { list-style:none; padding-left:0; }
 li { padding:5px 0 5px 26px; position:relative; }
 li:before { content:'☐'; position:absolute; left:4px; font-size:15px; }
 .note { color:#999; font-size:11px; margin-top:28px; }
</style></head><body>
<h1>Чек-лист проверки документов</h1>
<div class="obj">{{ property_title }}{% if address %} · {{ address }}{% endif %}
 {% if price %}· {{ price|money }}{% endif %}</div>
{% for section in sections %}
 <h2>{{ section.title }}</h2>
 <ul>{% for point in section.points %}<li>{{ point }}</li>{% endfor %}</ul>
{% endfor %}
<p class="note">Чек-лист сформирован автоматически {{ generated_at }}.
Носит справочный характер и не заменяет юридическую экспертизу.</p>
</body></html>"""

TEMPLATES = {
    "commercial_offer": COMMERCIAL_OFFER_TMPL,
    "object_report": OBJECT_REPORT_TMPL,
    "preliminary_contract": PRELIMINARY_CONTRACT_TMPL,
    "checklist": CHECKLIST_TMPL,
}

# TZ 32.8: the checklist covers what a buyer must verify before a deal. Sections
# differ for a new build (developer/escrow paperwork) and a resale (ownership
# history, encumbrances, family-law consents).
CHECKLIST_COMMON = [
    "Выписка из ЕГРН (актуальная, не старше 30 дней)",
    "Проверка объекта в реестре залогов и арестов",
    "Отсутствие задолженности по коммунальным платежам",
    "Технический паспорт / поэтажный план",
    "Соответствие планировки документам (нет неузаконенной перепланировки)",
]
CHECKLIST_NEW_BUILD = [
    "Проектная декларация застройщика",
    "Разрешение на строительство",
    "Договор долевого участия (ДДУ) по 214-ФЗ",
    "Эскроу-счёт открыт в уполномоченном банке",
    "Аккредитация объекта банком (если ипотека)",
    "Срок сдачи и ответственность за просрочку в договоре",
]
CHECKLIST_RESALE = [
    "Документ-основание права собственности продавца",
    "История переходов права (нет частой смены собственников)",
    "Согласие супруга(и) на сделку, если объект в совместной собственности",
    "Отсутствие зарегистрированных лиц (справка о снятии с учёта)",
    "Разрешение органов опеки, если затронуты права несовершеннолетних",
    "Проверка продавца на банкротство и исполнительные производства",
]


def checklist_sections(is_new_build: bool) -> list[dict[str, Any]]:
    """Build the checklist sections for an object."""
    specific = CHECKLIST_NEW_BUILD if is_new_build else CHECKLIST_RESALE
    return [
        {"title": "Новостройка" if is_new_build else "Вторичный рынок", "points": specific},
        {"title": "Общие проверки", "points": CHECKLIST_COMMON},
    ]


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
