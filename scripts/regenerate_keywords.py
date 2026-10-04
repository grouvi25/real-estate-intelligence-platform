"""Regenerate the keyword vocabulary of every city. ТЗ «Фильтрация сигналов» 2.5.

The geo-keywords prompt now asks for rental, hotel and tourism negatives; cities
added before that keep the old vocabulary until it is regenerated. Unlike adding a
city, this does not start source discovery again.

    docker compose exec app python scripts/regenerate_keywords.py           # show
    docker compose exec app python scripts/regenerate_keywords.py --apply   # write

Without --apply nothing is written: the AI answers differently every time, and a
worse vocabulary silently costs signals, so look at the counts first. A result
without city variations or intent phrases is never written even with --apply.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

LISTS = ("city_variations", "intent_phrases", "financial_terms", "property_terms",
         "negative_keywords")


def _counts(keywords: dict) -> str:
    return ", ".join(f"{k.split('_')[0]} {len((keywords or {}).get(k) or [])}" for k in LISTS)


async def main() -> int:
    parser = argparse.ArgumentParser(description="Перегенерировать ключевые слова городов")
    parser.add_argument("--apply", action="store_true", help="записать результат в базу")
    args = parser.parse_args()

    from sqlalchemy import select

    from app.database import async_session, engine
    from app.discovery.keyword_builder import generate_geo_keywords
    from app.models.geo_location import GeoLocation

    try:
        async with async_session() as session:
            geos = (await session.execute(select(GeoLocation))).scalars().all()
            for geo in geos:
                fresh = await generate_geo_keywords({
                    "city_name": geo.city_name,
                    "region": geo.region or "",
                    "market_type": (geo.market_profile or {}).get("type", "resort"),
                    "primary_segments": "family,investor,relocant",
                    "agency_id": str(geo.agency_id),
                })
                usable = bool(fresh.get("city_variations")) and bool(fresh.get("intent_phrases"))
                print(f"{geo.city_name}: было [{_counts(geo.keywords)}] → стало [{_counts(fresh)}]"
                      + ("" if usable else "  — пустой ответ ИИ, не записываю"))
                if args.apply and usable:
                    geo.keywords = fresh
            if args.apply:
                await session.commit()
                print("Записано.")
            else:
                print("Ничего не записано: запустите с --apply.")
    finally:
        await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
