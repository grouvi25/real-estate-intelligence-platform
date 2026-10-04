"""ТЗ «Avito + фильтрация сигналов» v1, блок 2: только покупка.

The acceptance list of 2.7 runs against the ТЗ's own vocabulary. Where the ТЗ's
proposed code would have failed its own list (a whole-word city match loses
«в Геленджике»), the behaviour asked for is kept and the mechanism is ours.
"""
import os

import pytest

from app.services.intent_scoring import city_mentioned, quick_filter

GEO = {
    "city_variations": ["Геленджик", "геленджик"],
    "intent_phrases": ["ищу квартиру", "купить", "куплю", "хочу купить"],
    "property_terms": ["квартира", "дом", "участок", "студия"],
    "financial_terms": ["млн", "бюджет", "ипотека"],
    "negative_keywords": ["сниму", "сдам", "аренда", "посуточно", "по суткам",
                          "гостевой дом", "гостиница", "хостел"],
}


@pytest.mark.parametrize("text", [
    "Ищу квартиру в Геленджике, бюджет 8 млн",
    "Хочу купить дом в Геленджике, рассматриваю",
    "хочу купить дом у моря, рассматриваю Геленджик",
    "Рассматриваю покупку квартиры в Геленджике, есть ипотека",
    "Переезжаем в Геленджик, ищем квартиру до 6 млн",
])
def test_buyers_pass(text):
    assert quick_filter(text, GEO)


@pytest.mark.parametrize("text", [
    "Сниму квартиру в Геленджике на лето",
    "Геленджик посуточно, 2-комнатная, центр, от 2000р",
    "Гостевой дом Геленджик, уютные номера",
    "Продаю квартиру в Геленджике",
    "Геленджикский рынок вырос на 3%",
    "Геленджикский санаторий предлагает путёвки, куплю не надо",
    "Ищу квартиру, бюджет 5 млн, рядом с морем",
    "Сдам 2-комнатную в Геленджике на сезон",
    "Хочу снять квартиру в Геленджике, бюджет 40 тысяч",
    "Отель в Геленджике: куплю тур, бюджет 50 тыс",
    "Наша компания продаёт квартиры в Геленджике, хотите купить — звоните",
])
def test_renters_sellers_and_adjectives_do_not(text):
    assert not quick_filter(text, GEO)


def test_declined_city_still_counts_but_not_inside_another_word():
    assert city_mentioned("квартира в геленджике", ["геленджик"])
    assert city_mentioned("из Геленджика в Анапу", ["анап"])
    assert not city_mentioned("канапе и диван", ["анап"])  # a stem inside a word
    assert not city_mentioned("анапский пляж", ["анап"])  # the adjective


def test_a_buyer_who_wants_the_seller_to_call_is_still_a_buyer():
    """«звоните» is on the ТЗ list but buyers write it too; it stays out."""
    assert quick_filter("Куплю дом в Геленджике до 12 млн, предложения звоните", GEO)


def test_prompt_asks_for_the_rental_and_advert_flags():
    from app.prompts.intent_scoring import SYSTEM_PROMPT_INTENT_SCORING

    assert '"is_rental":false' in SYSTEM_PROMPT_INTENT_SCORING
    assert '"is_advertisement":false' in SYSTEM_PROMPT_INTENT_SCORING
    assert "20-35" in SYSTEM_PROMPT_INTENT_SCORING  # market news, for monitoring


@pytest.mark.skipif(os.getenv("RUN_DB_TESTS") != "1", reason="requires live PostgreSQL")
@pytest.mark.asyncio
async def test_a_signal_the_model_flags_as_rental_leaves_the_queue(monkeypatch):
    from app.database import async_session, engine, run_migrations
    from app.models.agency import Agency
    from app.models.signal import Signal
    from app.services import ai_service, intent_scoring
    from worker.tasks.signal_tasks import _score_intent_batch

    answers = {
        "Сдам посуточно у моря": {"intent_score": 55, "segment": "family", "is_rental": True},
        "Застройщик: квартиры от 5 млн": {"intent_score": 40, "is_advertisement": True},
        "Куплю 2к в Геленджике до 8 млн": {"intent_score": 85, "segment": "family",
                                           "urgency": "hot", "is_rental": False},
    }

    async def fake_analysis(message, geo_profile):
        return answers[message["text"]]  # KeyError leaves other rows alone

    monkeypatch.setattr(ai_service.AIService, "provider_configured", property(lambda self: True))
    monkeypatch.setattr(intent_scoring, "full_intent_analysis", fake_analysis)

    await run_migrations()
    try:
        async with async_session() as s:
            agency = Agency(name="Фильтр аренды", base_city="Геленджик")
            s.add(agency)
            await s.flush()
            ids = {}
            for text in answers:
                sig = Signal(agency_id=agency.id, raw_text=text, status="new")
                s.add(sig)
                await s.flush()
                ids[text] = sig.id
            await s.commit()

        await _score_intent_batch(limit=100_000)

        async with async_session() as s:
            got = {text: await s.get(Signal, sid) for text, sid in ids.items()}
            rental, advert, buyer = got.values()
            assert (rental.status, rental.intent_score, rental.triage_reason) == ("rejected", 0, "аренда")
            assert (advert.status, advert.triage_reason) == ("rejected", "реклама")
            assert buyer.status == "new" and buyer.intent_score == 85
    finally:
        await engine.dispose()
