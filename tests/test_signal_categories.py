"""ТЗ «Сигналы» v1.0, апгрейд B: категории сигналов и фильтр по ним."""
import os
import re
import uuid
from pathlib import Path

import pytest

from app.services.signal_classifier import CATEGORY_KEYWORDS, classify_category

db_only = pytest.mark.skipif(os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL")


def test_classify_purchase_keywords():
    assert classify_category("Куплю квартиру в Геленджике") == "purchase"
    # the commonest buyer phrasing has none of the ТЗ's words
    assert classify_category("Ищу квартиру в Геленджике, бюджет 8 млн") == "purchase"


def test_classify_rental_keywords():
    assert classify_category("Сдам однушку у моря") == "rental"
    assert classify_category("посуточно, 2 человека") == "rental"


def test_classify_news_and_other():
    assert classify_category("ЦБ РФ поднял ставку, ипотека…") == "purchase"  # purchase words win
    assert classify_category("Госдума приняла закон о долевом строительстве") == "news"
    assert classify_category("Кто знает хорошего сантехника?") == "other"
    assert classify_category("") == "other"


def test_classify_competitor():
    assert classify_category("Обращался в Этажи — не перезвонили, куплю сам",
                             ["Этажи", "Инком"]) == "competitor"
    assert classify_category("этажи дома 5", ["Эт"]) == "other"  # too short to be a name


def test_migration_marks_old_signals_with_the_same_words():
    sql = (Path(__file__).resolve().parent.parent / "migrations" / "066_signal_category.sql"
           ).read_text(encoding="utf-8")
    for category, words in CATEGORY_KEYWORDS.items():
        m = re.search(r"~ '\(([^)]*)\)' THEN '" + category + "'", sql)
        assert m, category
        assert m.group(1).split("|") == words, category


async def _setup():
    from tests.helpers import unique_telegram_id

    from app.database import async_session, run_migrations
    from app.models.agency import Agency
    from app.models.manager import Manager
    from app.models.signal import Signal

    await run_migrations()
    async with async_session() as s:
        agency = Agency(name=f"Категории {uuid.uuid4().hex[:6]}", base_city="Сочи")
        s.add(agency)
        await s.flush()
        owner = Manager(agency_id=agency.id, name="Ольга", role="owner",
                        telegram_id=unique_telegram_id(), is_active=True)
        staff = Manager(agency_id=agency.id, name="Пётр", role="manager",
                        telegram_id=unique_telegram_id(), is_active=True)
        s.add_all([owner, staff])
        texts = ["Куплю дом в Сочи", "Сдам студию на лето", "Новый закон об ипотеке",
                 "Как пройти к морю?"]
        signals = [Signal(agency_id=agency.id, raw_text=t) for t in texts]  # no category given
        s.add_all(signals)
        await s.commit()
        return agency.id, owner.id, staff.id, [x.id for x in signals]


@db_only
@pytest.mark.asyncio
async def test_api_filter_by_category_and_manual_fix():
    from app.database import async_session, engine
    from app.dependencies import CurrentManager
    from app.exceptions import AppException
    from app.routers.signals import CategoryRequest, list_signals, set_signal_category

    try:
        agency_id, owner_id, staff_id, ids = await _setup()
        ctx = CurrentManager(str(staff_id), str(agency_id))
        async with async_session() as s:
            every = await list_signals(current=ctx, session=s)
            assert sorted(x["signal_category"] for x in every["signals"]) == \
                ["other", "purchase", "purchase", "rental"]  # set on insert, without AI
            only = await list_signals(category="purchase", current=ctx, session=s)
            assert {x["signal_category"] for x in only["signals"]} == {"purchase"} and only["count"] == 2
            two = await list_signals(category="rental,other", current=ctx, session=s)
            assert two["count"] == 2
            with pytest.raises(AppException):
                await list_signals(category="crypto", current=ctx, session=s)
            fixed = await set_signal_category(ids[3], CategoryRequest(category="news"),
                                              current=ctx, session=s)
            assert (fixed["signal_category"], fixed["signal_category_label"]) == ("news", "Новости")
            with pytest.raises(AppException):
                await set_signal_category(ids[3], CategoryRequest(category="spam"),
                                          current=ctx, session=s)
    finally:
        await engine.dispose()


@db_only
@pytest.mark.asyncio
async def test_agency_signal_filter_and_competitors():
    from app.database import async_session, engine
    from app.dependencies import CurrentManager
    from app.exceptions import AppException
    from app.routers.agency import SignalFilterRequest, get_signal_filter, update_signal_filter
    from app.services.signal_classifier import category_for

    try:
        agency_id, owner_id, staff_id, _ = await _setup()
        owner = CurrentManager(str(owner_id), str(agency_id))
        staff = CurrentManager(str(staff_id), str(agency_id))
        async with async_session() as s:
            assert (await get_signal_filter(current=staff, session=s))["enabled_cats"] == \
                ["purchase", "rental", "news", "competitor", "other"]
            with pytest.raises(AppException):  # the default is the owner's to change
                await update_signal_filter(SignalFilterRequest(enabled_cats=["purchase"]),
                                           current=staff, session=s)
            out = await update_signal_filter(SignalFilterRequest(
                enabled_cats=["news", "purchase", "purchase"],
                competitor_names=["  Этажи ", "этажи", "Юг-Риэлт", "x"]), current=owner, session=s)
            assert out["enabled_cats"] == ["purchase", "news"]
            assert out["competitor_names"] == ["Этажи", "Юг-Риэлт"]
            with pytest.raises(AppException):
                await update_signal_filter(SignalFilterRequest(enabled_cats=[]), current=owner, session=s)
            assert await category_for(s, agency_id, "В Юг-Риэлт сказали ждать") == "competitor"
    finally:
        await engine.dispose()
