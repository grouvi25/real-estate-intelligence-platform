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


# --- placeholder credentials must never select object storage -----------------

@pytest.mark.parametrize("value", ["dev", "DEV", "test", "dummy", "changeme", "todo",
                                   "your-key", "placeholder", "xxx", " dev "])
def test_placeholder_credentials_fall_back_to_local(monkeypatch, value):
    """Production shipped with YC_S3_ACCESS_KEY=dev. Once boto3 was installed the
    adapter took that at face value and every document upload died with
    SignatureDoesNotMatch."""
    import app.services.storage as st

    monkeypatch.setattr(st.config, "yc_s3_bucket", "realestate-prod")
    monkeypatch.setattr(st.config, "yc_s3_access_key", value)
    monkeypatch.setattr(st.config, "yc_s3_secret_key", "YCPqrs0123456789abcdefgh")
    assert st._creds_configured() is False

    monkeypatch.setattr(st.config, "yc_s3_access_key", "YCAJE0123456789abcdefghi")
    monkeypatch.setattr(st.config, "yc_s3_secret_key", value)
    assert st._creds_configured() is False


def test_short_credentials_are_treated_as_placeholders(monkeypatch):
    import app.services.storage as st

    monkeypatch.setattr(st.config, "yc_s3_bucket", "b")
    monkeypatch.setattr(st.config, "yc_s3_access_key", "short")
    monkeypatch.setattr(st.config, "yc_s3_secret_key", "alsoshort")
    assert st._creds_configured() is False


def test_real_looking_credentials_select_object_storage(monkeypatch):
    """Guard against over-filtering: real keys must still be honoured."""
    import app.services.storage as st

    monkeypatch.setattr(st.config, "yc_s3_bucket", "realestate-prod")
    monkeypatch.setattr(st.config, "yc_s3_access_key", "YCAJEabcdefghijklmnop123")
    monkeypatch.setattr(st.config, "yc_s3_secret_key", "YCPqrstuvwxyz0123456789abcdef")
    assert st._creds_configured() is True


def test_empty_credentials_fall_back_to_local(monkeypatch):
    import app.services.storage as st

    monkeypatch.setattr(st.config, "yc_s3_bucket", "")
    monkeypatch.setattr(st.config, "yc_s3_access_key", "YCAJEabcdefghijklmnop123")
    monkeypatch.setattr(st.config, "yc_s3_secret_key", "YCPqrstuvwxyz0123456789abcdef")
    assert st._creds_configured() is False
