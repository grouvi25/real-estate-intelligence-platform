"""Storage adapter tests (TZ 33). LocalStorage is exercised end-to-end; the
Yandex adapter selection logic is checked without hitting the network."""
import pytest

from app.services.storage import LocalStorage, get_storage


@pytest.mark.asyncio
async def test_local_storage_roundtrip(tmp_path):
    store = LocalStorage(base_dir=tmp_path)
    url = await store.upload("docs/offer.html", b"<h1>hi</h1>", "text/html")
    assert url.startswith("file://")
    assert await store.download("docs/offer.html") == b"<h1>hi</h1>"
    await store.delete("docs/offer.html")
    with pytest.raises(FileNotFoundError):
        await store.download("docs/offer.html")


@pytest.mark.asyncio
async def test_local_storage_rejects_traversal(tmp_path):
    store = LocalStorage(base_dir=tmp_path)
    with pytest.raises(ValueError):
        await store.upload("../escape.txt", b"x")


def test_get_storage_defaults_to_local_in_tests():
    # conftest sets dummy S3 creds, so the local fallback must be selected.
    assert isinstance(get_storage(), LocalStorage)
