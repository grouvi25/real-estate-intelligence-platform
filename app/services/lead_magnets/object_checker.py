"""LM-3: object legal due-diligence helper. TZ section 29.3.

Large classifieds (ЦИАН, Авито, ДомКлик) actively block automated scraping, so
for those we never scrape: we detect the platform and return a structured manual
due-diligence checklist plus an offer of a manager consultation. For other URLs
we make a best-effort parse with BeautifulSoup, wrapped in try/except so a failed
fetch degrades to the same checklist rather than erroring.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

# Площадки, которые блокируют парсинг — авто-проверку не выполняем.
BLOCKED_PLATFORMS = {
    "cian.ru": "ЦИАН",
    "avito.ru": "Авито",
    "domclick.ru": "ДомКлик",
    "domclick.com": "ДомКлик",
}

# Базовый чек-лист юридической чистоты объекта (152-ФЗ-нейтральный).
LEGAL_CHECKLIST = [
    {"key": "ownership", "title": "Право собственности",
     "hint": "Проверьте свежую выписку из ЕГРН (не старше 30 дней)"},
    {"key": "encumbrances", "title": "Обременения и аресты",
     "hint": "В выписке ЕГРН не должно быть залогов, арестов и запретов на регистрацию"},
    {"key": "history", "title": "История переходов права",
     "hint": "Частая смена собственников за короткий срок — повод насторожиться"},
    {"key": "registered", "title": "Прописанные лица",
     "hint": "Запросите справку о зарегистрированных, особое внимание — несовершеннолетним"},
    {"key": "matkapital", "title": "Материнский капитал",
     "hint": "Если использовался — должны быть выделены доли детям"},
    {"key": "spouse_consent", "title": "Согласие супруга",
     "hint": "Для совместно нажитого имущества нужно нотариальное согласие"},
    {"key": "pereplanirovka", "title": "Перепланировки",
     "hint": "Сверьте планировку с техпаспортом, узаконены ли изменения"},
    {"key": "debts", "title": "Долги по ЖКУ и взносам",
     "hint": "Запросите справку об отсутствии задолженности"},
    {"key": "bankruptcy", "title": "Банкротство продавца",
     "hint": "Проверьте продавца в реестре банкротов и на сайте ФССП"},
]


@dataclass
class ObjectCheckResult:
    url: str
    platform: str | None
    auto_check_available: bool
    checklist: list[dict]
    parsed: dict = field(default_factory=dict)
    risk_flags: list[str] = field(default_factory=list)
    recommendation: str = ""


def _detect_platform(host: str) -> str | None:
    host = host.lower().removeprefix("www.")
    for domain, label in BLOCKED_PLATFORMS.items():
        if host == domain or host.endswith("." + domain):
            return label
    return host or None


def check_object(url: str) -> ObjectCheckResult:
    """Analyse a listing URL and always return a due-diligence checklist."""
    parsed_url = urlparse(url if "://" in url else f"https://{url}")
    host = parsed_url.netloc
    platform = _detect_platform(host)

    blocked = any(
        host.lower().removeprefix("www.") == d or host.lower().endswith("." + d)
        for d in BLOCKED_PLATFORMS
    )

    result = ObjectCheckResult(
        url=url,
        platform=platform,
        auto_check_available=not blocked,
        checklist=LEGAL_CHECKLIST,
    )

    if blocked:
        result.recommendation = (
            f"Автоматическая проверка объявлений на площадке «{platform}» недоступна. "
            "Пройдите чек-лист вручную или закажите бесплатную проверку у нашего юриста."
        )
        return result

    # Best-effort parse for non-blocked pages. Never let a network/parse error
    # break the endpoint — the checklist is the primary value.
    try:  # pragma: no cover - network path not exercised in tests
        import httpx
        from bs4 import BeautifulSoup

        resp = httpx.get(url, timeout=8.0, follow_redirects=True,
                         headers={"User-Agent": "Mozilla/5.0 (REIP object checker)"})
        soup = BeautifulSoup(resp.text, "html.parser")
        title = soup.title.string.strip() if soup.title and soup.title.string else None
        result.parsed = {"title": title, "status_code": resp.status_code}
        result.recommendation = "Проверьте объект по чек-листу ниже перед внесением аванса."
    except Exception:  # pragma: no cover
        result.recommendation = (
            "Не удалось загрузить страницу автоматически. "
            "Воспользуйтесь чек-листом для самостоятельной проверки."
        )

    return result
