"""Tests for two-stage intent scoring (quick_filter + AI stage)."""
import pytest

from app.services.intent_scoring import full_intent_analysis, quick_filter

GEO = {
    "city_variations": ["геленджик", "гдж"],
    "intent_phrases": ["ищу", "хочу купить", "присматриваю"],
    "financial_terms": ["ипотека", "бюджет", "млн"],
    "property_terms": ["квартира", "студия", "дом"],
}


def test_quick_filter_passes_real_buyer():
    assert quick_filter("Ищу квартиру в Геленджике до 8 млн", GEO) is True


def test_quick_filter_requires_city():
    assert quick_filter("ищу квартиру до 8 млн", GEO) is False


def test_quick_filter_rejects_seller():
    assert quick_filter("Продаю квартиру в Геленджике, звоните", GEO) is False


def test_quick_filter_requires_intent_or_financial_or_property():
    assert quick_filter("Геленджик хороший город", GEO) is False


def test_quick_filter_empty():
    assert quick_filter("", GEO) is False


# Verbatim messages the collector pulled from Геленджик chats on the first live
# run. All 25 collected messages were noise; these are representative.
LIVE_NOISE = [
    'Мебель "Магнат" пр. Геленджикский, д. 9 Тел.: 8 (928) 275-72-78 Столы, стулья, '
    "люстры, кресла-кровати, кровати: от эконом до элит, матрасы",
    "Бегония декоративно-лиственная, селекционная домашняя коллекция 200₽/300₽ "
    "г.Геленджик 89996358613 самовывоз, Яндекс курьер",
    "#ищу жильё ✅ Геленджик; ✅ Район любой; ✅ Квартира/комната/дом; ✅ Мама и дочка",
    "#сниму #Геленджик #Кабардинка Смотрим все районы. На круглый год. "
    "Семья с двумя детьми. 2-к квартиру или часть дома",
    "#ищу жильё ✅ ГЕЛЕНДЖИК; ✅ Квартиру; ✅ Семья, дети 3 и 7 лет; "
    "✅ На круглый год; 💵 БЮДЖЕТ до 25.000₽",
]

LIVE_BUYERS = [
    "Ищу квартиру в Геленджике до 8 млн, рассматриваем ипотеку",
    "Переезжаем в Геленджик, нужен дом с участком",
    "Хочу купить студию в Геленджике под сдачу",
    "Куплю 2-к квартиру в Геленджике, бюджет 9 млн",
    "Рассматриваем покупку дома в Геленджике, есть маткапитал",
]

# Shaped like the sanitised vocabularies the keyword builder stores for Геленджик.
LIVE_GEO = {
    "city_variations": ["Геленджик"],
    "intent_phrases": ["ищу квартиру", "куплю", "подскажите район", "переезжаем", "хочу купить"],
    "property_terms": ["новостройк", "вторичк", "дома", "участк", "студи"],
    "financial_terms": ["ипотек", "квартир", "дом", "участок", "маткапитал"],
    "negative_keywords": ["сдам", "аренда", "посуточно", "работа", "продам"],
}


@pytest.mark.parametrize("text", LIVE_NOISE)
def test_quick_filter_drops_live_noise(text):
    """Adverts and renters must not reach the paid AI stage."""
    assert quick_filter(text, LIVE_GEO) is False


@pytest.mark.parametrize("text", LIVE_BUYERS)
def test_quick_filter_keeps_live_buyers(text):
    assert quick_filter(text, LIVE_GEO) is True


def test_quick_filter_requires_purchase_intent():
    """A property word alone is not enough -- that is what let the furniture
    advert through ("Геленджикский" + the stem "дома" inside "домашняя")."""
    assert quick_filter("Продаётся мебель в Геленджике, столы и кровати", LIVE_GEO) is False
    assert quick_filter("Куплю квартиру в Геленджике", LIVE_GEO) is True


def test_quick_filter_uses_geo_negative_keywords():
    """The per-geo vocabulary must apply, not just the module baseline.

    The baseline has "продаю" but not "продам", so this seller slipped through on
    the live Геленджик geo even though its generated negative_keywords listed it.
    """
    geo = {**GEO, "negative_keywords": ["хостел"]}
    message = "Куплю квартиру в Геленджике, рядом хостел"

    assert quick_filter(message, GEO) is True  # baseline has no such term
    assert quick_filter(message, geo) is False
    # A real buyer is unaffected.
    assert quick_filter("Ищу квартиру в Геленджике до 8 млн", geo) is True


@pytest.mark.asyncio
async def test_full_intent_analysis_parses_ai(monkeypatch):
    from app.services.ai_service import AIService

    async def fake_complete(self, system, user, module, agency_id="global"):
        assert module == "intent_scoring"
        assert "Геленджик" in user
        return '{"intent_score": 85, "segment": "family", "urgency": "hot"}'

    monkeypatch.setattr(AIService, "complete", fake_complete)
    result = await full_intent_analysis(
        {"text": "ищу квартиру", "source_name": "Чат"}, {"city_name": "Геленджик"}
    )
    assert result["intent_score"] == 85
    assert result["segment"] == "family"


@pytest.mark.asyncio
async def test_full_intent_analysis_bad_json_fallbacks(monkeypatch):
    from app.services.ai_service import AIService

    async def fake_complete(self, system, user, module, agency_id="global"):
        return "the model rambled without json"

    monkeypatch.setattr(AIService, "complete", fake_complete)
    result = await full_intent_analysis({"text": "x"}, {"city_name": "Сочи"})
    assert result["intent_score"] == 0
    assert result["segment"] == "not_buyer"
    assert result["parse_error"] is True


# Verbatim from the second live collection, over real Геленджик property chats.
# 15 messages reached the queue and 14 were noise.
LIVE_SELLERS = [
    "🔴 СОБСТВЕННИК! Срочно продам видовой участок 11.2 сот. (ИЖС) у моря! "
    "Цена снижена, пока горит моя встречная покупка! Реальному покупателю — торг на месте.",
    "‼️Город-курорт Геленджик!!! 🔥Лучшее соотношение «ЦЕНА - КАЧЕСТВО» "
    "✅Лучший район города - Толстый мыс; ✅ЖК «Черноморский»; ✅2-х ком квартира",
    "Продам ‼️г Краснодар «Город в городе» ‼️ЖК «Сармат» ✅Полноценная 3-х ком "
    "квартира S - 77.7 m2, Геленджик рядом",
]

LIVE_BUYER = ("Запрос: квартира в г.Геленджик бюджет до 5 млн. ( наличка), "
              "предложения писать в личных сообщениях. Спасибо #куплю")


@pytest.mark.parametrize("text", LIVE_SELLERS)
def test_quick_filter_drops_live_sellers_and_adverts(text):
    """"встречная покупка" and "покупателю" matched the bare stem "покупк", and
    the geo's own negatives had lost "продам" between two AI regenerations."""
    assert quick_filter(text, LIVE_GEO) is False


def test_quick_filter_keeps_the_live_buyer():
    assert quick_filter(LIVE_BUYER, LIVE_GEO) is True


def test_seller_markers_do_not_depend_on_the_geo_vocabulary():
    """The per-geo list is regenerated by the AI and cannot be relied on; the
    baseline has to carry the unmistakable seller words itself."""
    from app.services.intent_scoring import NEGATIVE_KEYWORDS

    for word in ("продам", "продаю", "продаётся", "собственник"):
        assert word in NEGATIVE_KEYWORDS

    bare_geo = {**LIVE_GEO, "negative_keywords": []}
    assert quick_filter("Продам квартиру в Геленджике, торг", bare_geo) is False


def test_ambiguous_purchase_stems_are_not_treated_as_intent():
    from app.services.intent_scoring import BUY_INTENT_KEYWORDS

    # Bare "покупк"/"купить" match seller and advertising copy just as well.
    assert "покупк" not in BUY_INTENT_KEYWORDS
    assert "купить" not in BUY_INTENT_KEYWORDS
    assert "куплю" in BUY_INTENT_KEYWORDS
    assert "хочу купить" in BUY_INTENT_KEYWORDS


# --- repost dedup ------------------------------------------------------------

def test_fingerprint_collapses_reposts_of_the_same_listing():
    """One advert reached the live queue five times: same body, new message id."""
    from app.services.intent_scoring import content_fingerprint

    original = "‼️Город-курорт Геленджик!!! ЖК «Черноморский», 2-х ком квартира"
    reposted = "Город-курорт  Геленджик!!!   ЖК «Черноморский», 2-х ком квартира  "

    assert content_fingerprint(original) == content_fingerprint(reposted)
    assert content_fingerprint(original) != content_fingerprint(original + " ещё дом")


def test_fingerprint_is_stable_and_handles_empty_text():
    from app.services.intent_scoring import content_fingerprint

    assert content_fingerprint("Куплю") == content_fingerprint("куплю!")
    assert content_fingerprint("") == content_fingerprint(None)
    assert len(content_fingerprint("x")) == 64
