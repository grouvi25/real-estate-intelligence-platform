"""Площадки из ТЗ без рабочего открытого доступа (ТЗ разрешает три заглушки).

Each stub says why, so the run log and the owner's screen show a reason rather
than a silent zero. Checked 11.10.2026.
"""
from __future__ import annotations

from app.services.discovery.searchers.base import StubSearcher
from app.services.discovery.types import CLASSIFIEDS, OTZOVIK, WORDSTAT


class ClassifiedsSearcher(StubSearcher):
    """Суб-поиск 4. Avito and ЦИАН have no public RSS any more (404), and their
    listing pages sit behind an anti-bot wall. The agency's own Avito listings
    come in through the Avito API already (app/services/avito_sync.py)."""
    platform = CLASSIFIEDS
    title = "Доски объявлений (Avito, ЦИАН)"
    why_unavailable = "открытых лент нет, страницы закрыты антиботом"


class OtzovikSearcher(StubSearcher):
    """Суб-поиск 8. otzovik.com forbids its search to robots in robots.txt
    (Disallow: /*search_text=), and the ТЗ itself requires honouring robots.txt;
    irecommend.ru answers its search with a captcha. Nothing is left to read
    without breaking one rule or the other."""
    platform = OTZOVIK
    title = "Отзовики (otzovik, irecommend)"
    why_unavailable = "otzovik запрещает поиск в robots.txt, irecommend отвечает капчей"


class WordstatWatcher(StubSearcher):
    """Суб-поиск 10. Wordstat API access is granted on application and is paid;
    REIP has no key. The ТЗ uses it only to re-weight queries, never to find a
    source, so discovery loses nothing but that hint until a key arrives."""
    platform = WORDSTAT
    title = "Яндекс Wordstat (тренды запросов)"
    why_unavailable = "нужен доступ к API Wordstat"
