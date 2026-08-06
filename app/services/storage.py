"""Object storage abstraction. TZ section 33 (Yandex Object Storage / S3).

A small StorageAdapter interface with two implementations:
- LocalStorage: writes under a base directory. Default for dev/CI (no creds, no
  network) so uploads work without boto3.
- YandexObjectStorage: S3-compatible client for Yandex Object Storage. boto3 is
  imported lazily and listed as an optional dependency.

get_storage() picks Yandex when real S3 credentials are configured, otherwise
LocalStorage. All object keys are treated as opaque, forward-slash paths.
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from pathlib import Path

import structlog

from app.config import config

logger = structlog.get_logger()

# Placeholder values that must not be mistaken for real credentials. "dev" is on
# the list because production shipped with YC_S3_ACCESS_KEY=dev: once boto3 was
# installed the adapter took those at face value, and every document upload died
# with SignatureDoesNotMatch. A credential shorter than a real one is treated the
# same way -- Yandex keys are long, so anything tiny is a placeholder.
_DUMMY_MARKERS = ("dummy", "changeme", "test", "dev", "todo", "xxx", "your", "placeholder")
_MIN_CREDENTIAL_LEN = 12


class StorageAdapter(ABC):
    @abstractmethod
    async def upload(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        """Store ``data`` at ``key``; return a URL or key that locates it."""

    @abstractmethod
    async def download(self, key: str) -> bytes:
        """Return the bytes stored at ``key``."""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Remove the object at ``key`` (idempotent)."""

    @abstractmethod
    def url(self, key: str) -> str:
        """Return a stable URL/locator for ``key`` (no I/O)."""


class LocalStorage(StorageAdapter):
    """Filesystem-backed storage for development and tests."""

    def __init__(self, base_dir: str | Path = "storage_data"):
        self.base = Path(base_dir)
        self.base.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Prevent path traversal: keys are relative, no ".." segments.
        safe = Path(key.replace("\\", "/"))
        if safe.is_absolute() or ".." in safe.parts:
            raise ValueError(f"Недопустимый ключ хранилища: {key}")
        return self.base / safe

    async def upload(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, data)
        logger.info("LocalStorage upload", key=key, bytes=len(data))
        return self.url(key)

    async def download(self, key: str) -> bytes:
        return await asyncio.to_thread(self._path(key).read_bytes)

    async def delete(self, key: str) -> None:
        path = self._path(key)
        if path.exists():
            await asyncio.to_thread(path.unlink)

    def url(self, key: str) -> str:
        return f"file://{self._path(key).resolve()}"


class YandexObjectStorage(StorageAdapter):
    """S3-compatible Yandex Object Storage adapter (boto3, lazy)."""

    def __init__(self):
        self.bucket = config.yc_s3_bucket
        self.endpoint = config.yc_s3_endpoint
        self.region = config.yc_s3_region
        self._client = None

    def _get_client(self):
        if self._client is None:
            import boto3  # noqa: PLC0415

            self._client = boto3.client(
                "s3",
                endpoint_url=self.endpoint,
                region_name=self.region,
                aws_access_key_id=config.yc_s3_access_key,
                aws_secret_access_key=config.yc_s3_secret_key,
            )
        return self._client

    async def upload(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        def _put():
            self._get_client().put_object(Bucket=self.bucket, Key=key, Body=data,
                                          ContentType=content_type)

        await asyncio.to_thread(_put)
        logger.info("YandexObjectStorage upload", key=key, bytes=len(data))
        return self.url(key)

    async def download(self, key: str) -> bytes:
        def _get():
            resp = self._get_client().get_object(Bucket=self.bucket, Key=key)
            return resp["Body"].read()

        return await asyncio.to_thread(_get)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(
            lambda: self._get_client().delete_object(Bucket=self.bucket, Key=key)
        )

    def url(self, key: str) -> str:
        return f"{self.endpoint}/{self.bucket}/{key}"


def _creds_configured() -> bool:
    """True only when all three S3 settings look like real credentials."""
    for value in (config.yc_s3_bucket, config.yc_s3_access_key, config.yc_s3_secret_key):
        if not value:
            return False
        lowered = value.strip().lower()
        if lowered in _DUMMY_MARKERS or any(lowered.startswith(m) for m in _DUMMY_MARKERS):
            return False
    # The bucket name may legitimately be short; the keys never are.
    for secret in (config.yc_s3_access_key, config.yc_s3_secret_key):
        if len(secret.strip()) < _MIN_CREDENTIAL_LEN:
            return False
    return True


_storage: StorageAdapter | None = None


def get_storage() -> StorageAdapter:
    """Return the process-wide storage adapter (Yandex if configured, else local)."""
    global _storage
    if _storage is None:
        _storage = YandexObjectStorage() if _creds_configured() else LocalStorage()
        logger.info("Storage adapter selected", adapter=type(_storage).__name__)
    return _storage
