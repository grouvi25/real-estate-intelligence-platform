"""RSS and YouTube collectors (TZ section 3 manifest).

Both source types were allowed by the schema from the first migration and
nothing ever read one: a feed added on the Источники screen produced a row that
sat there for ever, and a YouTube channel the same.
"""
import pytest

from app.config import config

RSS_SAMPLE = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel>
  <title>Новости Геленджика</title>
  <item>
    <title>Ищу двухкомнатную квартиру в Геленджике до 8 млн</title>
    <description>&lt;p&gt;Наличные, рассматриваю Тонкий мыс&lt;/p&gt;</description>
    <link>https://forum.example/t/1</link>
    <guid>forum-1</guid>
    <pubDate>Wed, 06 Aug 2026 09:12:00 +0000</pubDate>
  </item>
  <item>
    <title>Погода на выходные</title>
    <description>Ясно, +27</description>
    <link>https://forum.example/t/2</link>
    <guid>forum-2</guid>
  </item>
</channel></rss>"""

ATOM_SAMPLE = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Куплю дом в Дивноморском</title>
    <summary>До 12 млн, семья с детьми</summary>
    <link href="https://atom.example/1"/>
    <id>atom-1</id>
    <updated>2026-08-06T09:12:00Z</updated>
  </entry>
</feed>"""


def test_an_rss_feed_is_read():
    from app.collectors.rss_collector import parse_feed

    items = parse_feed(RSS_SAMPLE)

    assert [i["id"] for i in items] == ["forum-1", "forum-2"]
    first = items[0]
    assert first["url"] == "https://forum.example/t/1"
    # Feeds routinely put HTML in the description; the AI reads text.
    assert "<p>" not in first["text"]
    assert "Наличные" in first["text"]
    assert first["published_at"] is not None


def test_an_atom_feed_is_read_the_same_way():
    """Two spellings of the same thing; the collector should not care."""
    from app.collectors.rss_collector import parse_feed

    items = parse_feed(ATOM_SAMPLE)

    assert len(items) == 1
    assert items[0]["url"] == "https://atom.example/1"
    assert "Дивноморском" in items[0]["text"]


def test_a_broken_feed_does_not_take_the_run_with_it():
    """Feeds are exactly the kind of input that arrives malformed."""
    from app.collectors.rss_collector import parse_feed

    assert parse_feed("<rss><channel><item><title>обрыв") == []
    assert parse_feed("") == []


def test_youtube_is_a_no_op_without_a_key(monkeypatch):
    """Same contract as every other collector: no credentials, no calls."""
    from app.collectors.youtube_collector import YoutubeCollector

    monkeypatch.setattr(config, "youtube_api_key", None)
    assert YoutubeCollector().is_available() is False


def test_the_youtube_channel_comes_from_the_id_or_the_url():
    from types import SimpleNamespace

    from app.collectors.youtube_collector import YoutubeCollector

    src = lambda **kw: SimpleNamespace(**{"external_id": None, "source_url": "", **kw})  # noqa: E731
    assert YoutubeCollector._channel_id(src(external_id="UC123")) == "UC123"
    assert YoutubeCollector._channel_id(
        src(source_url="https://youtube.com/channel/UC456/videos")) == "UC456"
    assert YoutubeCollector._channel_id(src()) is None


@pytest.mark.parametrize("channel", ["rss", "youtube"])
def test_the_signal_bus_knows_these_channels(channel):
    """ingest_content drops a message whose channel has no adapter — which is
    what would have happened to everything these collectors read."""
    from app.services.channels import get_channel_adapter

    adapter = get_channel_adapter(channel)
    assert adapter is not None
    # Read-only: a feed has no reply surface, and a YouTube comment is answered
    # from the channel's own account.
    assert adapter.reply_supported() is False


def test_the_normalised_item_keeps_its_link_and_time():
    from datetime import datetime, timezone

    from app.services.channels import get_channel_adapter

    when = datetime(2026, 8, 6, 9, 12, tzinfo=timezone.utc)
    norm = get_channel_adapter("rss").normalize({
        "id": "forum-1", "url": "https://forum.example/t/1", "text": "Ищу квартиру",
        "content_type": "post", "published_at": when, "author_name": None,
    })

    assert norm.external_id == "forum-1"
    assert norm.url == "https://forum.example/t/1"
    assert norm.published_at == when


def test_the_collectors_are_scheduled():
    from worker.celery_app import celery_app

    tasks = {e["task"] for e in celery_app.conf.beat_schedule.values()}
    assert "worker.tasks.collector_tasks.collect_web_sources" in tasks
