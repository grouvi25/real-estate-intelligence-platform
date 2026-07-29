"""Yandex Cloud Logging shipping. TZ 24 / 35.11.

TZ 35.11 wants Cloud Logging to receive the log stream. Inside Yandex Cloud
stdout is collected automatically; this deployment is a plain VPS, where nothing
collected anything. The sink is credential-gated, so the important properties are
that it stays off without real credentials and that it can never break the app
when it is on.
"""
import asyncio
import json

import pytest

from app.services import yc_logging


@pytest.fixture(autouse=True)
def _clean_sink():
    yc_logging._sink = None
    yield
    yc_logging._sink = None


def _write_key(tmp_path):
    key = tmp_path / "sa-key.json"
    key.write_text(json.dumps({
        "id": "key-id", "service_account_id": "sa-id", "private_key": "-----BEGIN...",
    }), encoding="utf-8")
    return key


def test_disabled_without_a_key_file(monkeypatch, tmp_path):
    monkeypatch.setattr(yc_logging.config, "yc_folder_id", "b1greal")
    monkeypatch.setattr(yc_logging.config, "yc_service_account_key_file", str(tmp_path / "nope.json"))
    assert yc_logging.is_configured() is False
    assert yc_logging.init_yc_logging() is False


@pytest.mark.parametrize("folder", ["dev", "", "test", "DUMMY"])
def test_disabled_for_placeholder_folder_ids(monkeypatch, tmp_path, folder):
    """Production ships with YC_FOLDER_ID=dev; that must not look configured."""
    monkeypatch.setattr(yc_logging.config, "yc_folder_id", folder)
    monkeypatch.setattr(yc_logging.config, "yc_service_account_key_file", str(_write_key(tmp_path)))
    assert yc_logging.is_configured() is False


def test_enabled_with_real_credentials(monkeypatch, tmp_path):
    monkeypatch.setattr(yc_logging.config, "yc_folder_id", "b1gxxxxxxxxx")
    monkeypatch.setattr(yc_logging.config, "yc_service_account_key_file", str(_write_key(tmp_path)))
    assert yc_logging.is_configured() is True


def test_processor_passes_the_event_through_untouched():
    """stdout must keep its JSON whether or not shipping is on."""
    event = {"event": "HTTP request", "level": "info", "status_code": 200}
    assert yc_logging.yc_processor(None, "info", event) is event

    yc_logging._sink = yc_logging.YandexCloudLogSink("folder", __import__("pathlib").Path("x"))
    out = yc_logging.yc_processor(None, "info", event)
    assert out is event
    assert yc_logging._sink.queue.qsize() == 1
    # A copy is queued, so later mutation of the entry cannot alter what ships.
    assert yc_logging._sink.queue.get_nowait() is not event


def test_a_full_queue_drops_entries_instead_of_blocking():
    """A Cloud Logging outage must cost memory, not the process."""
    import pathlib

    sink = yc_logging.YandexCloudLogSink("folder", pathlib.Path("x"))
    sink.queue = asyncio.Queue(maxsize=2)
    for i in range(5):
        sink.enqueue({"event": f"e{i}"})

    assert sink.queue.qsize() == 2
    assert sink.dropped == 3


@pytest.mark.asyncio
async def test_drain_batches_what_is_queued():
    import pathlib

    sink = yc_logging.YandexCloudLogSink("folder", pathlib.Path("x"))
    for i in range(3):
        sink.enqueue({"event": f"e{i}"})

    batch = await sink._drain()
    assert [e["event"] for e in batch] == ["e0", "e1", "e2"]
    assert sink.queue.empty()


@pytest.mark.asyncio
async def test_write_survives_a_failing_ingestion_endpoint():
    """Never raise out of the logging path."""
    import pathlib

    sink = yc_logging.YandexCloudLogSink("folder", pathlib.Path("x"))

    class _Client:
        async def post(self, *a, **k):
            raise RuntimeError("cloud unreachable")

    # Token exchange fails first, so the write is skipped -- and neither raises.
    await sink._write(_Client(), [{"event": "e", "level": "info"}])


@pytest.mark.asyncio
async def test_write_maps_levels_and_payload(monkeypatch):
    import pathlib

    sink = yc_logging.YandexCloudLogSink("b1gfolder", pathlib.Path("x"))
    monkeypatch.setattr(sink, "_iam_token", lambda client: _async_return("token"))
    captured = {}

    class _Client:
        async def post(self, url, json=None, headers=None, timeout=None):
            captured["url"], captured["body"], captured["headers"] = url, json, headers

            class _R:
                def raise_for_status(self):
                    return None
            return _R()

    await sink._write(_Client(), [
        {"event": "boom", "level": "error", "timestamp": "2026-07-28T00:00:00Z", "extra": 1},
        {"event": "hi", "level": "warning", "timestamp": "2026-07-28T00:00:01Z"},
    ])

    assert captured["url"] == yc_logging.INGEST_URL
    assert captured["headers"]["Authorization"] == "Bearer token"
    assert captured["body"]["destination"] == {"folderId": "b1gfolder"}
    levels = [e["level"] for e in captured["body"]["entries"]]
    assert levels == ["ERROR", "WARN"]  # structlog names -> Cloud Logging names
    # The whole event dict travels as the payload, not just the message.
    assert captured["body"]["entries"][0]["jsonPayload"]["extra"] == 1


def _async_return(value):
    async def _coro():
        return value
    return _coro()
