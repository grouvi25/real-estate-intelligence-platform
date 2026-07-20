"""LM-3: object listing fetcher. TZ section 29.2 (exact spec).

Fetches listing text for AI analysis. ЦИАН/Авито/ДомКлик block scraping, so for
those we return (False, manual-instruction) and the router asks the user to paste
the text. The AI analysis itself is done in the router via SYSTEM_PROMPT_OBJECT_ANALYSIS.
"""
from __future__ import annotations

import structlog

logger = structlog.get_logger()

BLOCKED = ["cian.ru", "avito.ru", "domclick.ru"]


async def fetch_listing_text(url: str) -> tuple[bool, str]:
    domain = url.split("/")[2].replace("www.", "") if "://" in url else ""
    if any(b in domain for b in BLOCKED):
        return False, f"{domain} блокирует автоматическое чтение. Скопируйте текст вручную."
    try:
        import httpx
        from bs4 import BeautifulSoup

        async with httpx.AsyncClient(
            headers={"User-Agent": "Mozilla/5.0 (compatible; RE-Check/1.0)"},
            timeout=15.0,
            follow_redirects=True,
        ) as client:
            resp = await client.get(url)
        if resp.status_code == 403:
            return False, "Сайт вернул 403. Скопируйте текст объявления вручную."
        if resp.status_code != 200:
            return False, f"Ошибка загрузки ({resp.status_code}). Вставьте текст вручную."
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "iframe"]):
            tag.decompose()
        return True, soup.get_text(separator="\n", strip=True)[:3000]
    except Exception:  # noqa: BLE001
        return False, "Не удалось загрузить страницу. Вставьте текст объявления вручную."
