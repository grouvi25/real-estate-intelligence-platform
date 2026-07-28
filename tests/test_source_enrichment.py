"""Source candidates must be judged on content, not just a title. TZ 15.2.

The evaluation prompt asks for sample messages, but the search only ever returned
a title, so scoring was blind. On the live Геленджик run that cost the single
genuinely relevant source: "Недвижимость Геленджика" scored 0 by name and 80 once
three of its messages were attached. Two chats both named "Барахолка Геленджик"
scored 40 and 0 in the same run, which is the same problem showing up as noise.
"""
import pytest

from app.collectors.telegram_collector import TelegramCollector


class _FakeMessage:
    def __init__(self, text):
        self.message = text


class _FakeClient:
    """Yields canned messages; raises for chats that cannot be read."""

    def __init__(self, by_username, unreadable=()):
        self.by_username = by_username
        self.unreadable = set(unreadable)
        self.requested = []

    def iter_messages(self, username, limit=0):
        self.requested.append((username, limit))
        if username in self.unreadable:
            raise RuntimeError("chat is private")

        async def gen():
            for text in self.by_username.get(username, []):
                yield _FakeMessage(text)

        return gen()


@pytest.mark.asyncio
async def test_samples_are_attached_to_candidates():
    client = _FakeClient({
        "realty_gel": [
            "Куплю двухкомнатную в Геленджике до 9 млн, рассмотрю Толстый мыс",
            "Подскажите нормального юриста по сделке",
            "Продаётся дом 120 м2, звоните",
        ],
    })
    cands = [{"username": "realty_gel", "name": "Недвижимость Геленджика"}]

    await TelegramCollector()._enrich_candidates(client, cands)

    assert len(cands[0]["samples"]) == 3
    assert "Куплю двухкомнатную" in cands[0]["samples"][0]


@pytest.mark.asyncio
async def test_short_messages_are_skipped_and_long_ones_truncated():
    client = _FakeClient({
        "chat": ["ок", "+", "да", "К" * 500, "Ищу квартиру в Геленджике для семьи"],
    })
    cands = [{"username": "chat", "name": "Чат"}]

    await TelegramCollector()._enrich_candidates(client, cands)

    samples = cands[0]["samples"]
    # "ок"/"+"/"да" carry no signal about what the chat is for.
    assert all(len(s) > 20 for s in samples)
    assert all(len(s) <= 280 for s in samples)
    assert len(samples) == 2


@pytest.mark.asyncio
async def test_an_unreadable_chat_does_not_break_the_run():
    client = _FakeClient({"ok_chat": ["Куплю квартиру в Геленджике срочно"]},
                         unreadable={"private_chat"})
    cands = [
        {"username": "private_chat", "name": "Закрытый"},
        {"username": "ok_chat", "name": "Открытый"},
    ]

    await TelegramCollector()._enrich_candidates(client, cands)

    assert cands[0].get("samples", []) == []
    assert len(cands[1]["samples"]) == 1


@pytest.mark.asyncio
async def test_enrichment_stops_at_the_sample_limit():
    client = _FakeClient({"busy": [f"Сообщение номер {i} про недвижимость" for i in range(50)]})
    cands = [{"username": "busy", "name": "Активный"}]

    await TelegramCollector()._enrich_candidates(client, cands, samples=3)

    assert len(cands[0]["samples"]) == 3
    # The read is bounded, not "the whole history until 3 long ones turn up".
    assert client.requested[0][1] == 12


def test_evaluation_prompt_separates_buyers_from_renters():
    """Scoring on geography alone put a long-term rental chat into production at
    80; purpose is the primary axis now."""
    from app.prompts.source_evaluation import SYSTEM_PROMPT_TELEGRAM_SOURCE_EVAL as P

    assert "не выше 15" in P
    assert "аренды" in P and "арендаторы, а не покупатели" in P
    # Flea markets belong in the sandbox: mixed content, but people do post
    # "куплю квартиру" there, and stage-1 filtering separates that now.
    assert "барахолки" in P.lower()
    assert "песочницу" in P
