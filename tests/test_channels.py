"""Channel adapter tests (Signal Bus addendum). normalize() is pure."""
from app.services.channels import SUPPORTED_CHANNELS, get_channel_adapter


def test_registry_has_all_channels():
    assert set(SUPPORTED_CHANNELS) == {
        # answerable
        "avito", "cian", "telegram", "max", "vk",
        # read-only: collected from, never answered on
        "youtube", "rss",
    }
    assert get_channel_adapter("AVITO").channel == "avito"
    assert get_channel_adapter("unknown") is None


def test_avito_normalize():
    a = get_channel_adapter("avito")
    n = a.normalize({
        "id": 777, "title": "Продам 2к", "description": "у моря",
        "url": "https://avito.ru/777", "user_id": "u1", "price": 7000000,
    })
    assert n.channel == "avito"
    assert n.external_id == "777"
    assert "Продам 2к" in n.raw_content and "у моря" in n.raw_content
    assert n.author_hash and len(n.author_hash) == 32
    assert n.meta["price"] == 7000000
    assert a.reply_supported() is False


def test_telegram_normalize_and_reply_supported():
    tg = get_channel_adapter("telegram")
    n = tg.normalize({
        "message_id": 5, "chat": {"id": 100}, "from": {"id": 42, "username": "ivan"},
        "text": "Ищу квартиру", "date": 1700000000,
    })
    assert n.external_id == "100:5"
    assert n.raw_content == "Ищу квартиру"
    assert n.author_display_name == "ivan"
    assert n.published_at is not None
    assert tg.reply_supported() is True


def test_vk_normalize_builds_external_id():
    vk = get_channel_adapter("vk")
    n = vk.normalize({"id": 55, "owner_id": -10, "from_id": 7, "text": "хочу купить", "date": 1700000000})
    assert n.external_id == "-10_55"
    assert n.url.endswith("-10_55")


def test_author_hash_stable_and_none_safe():
    from app.services.channels.base import author_hash

    assert author_hash("vk", None) is None
    assert author_hash("vk", 7) == author_hash("vk", 7)
    assert author_hash("vk", 7) != author_hash("avito", 7)
