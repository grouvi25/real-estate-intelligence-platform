"""Ship structured logs to Yandex Cloud Logging. TZ 24 / 35.11.

TZ 35.11 asks that "Structlog пишет JSON, Yandex Cloud Logging принимает потоки".
Inside Yandex Cloud stdout is collected automatically, but this deployment runs
on a plain VPS, so nothing was collecting anything -- logs only ever existed in
`docker logs`.

This module adds a structlog processor that also pushes each entry to Cloud
Logging's ingestion API. It is credential-gated exactly like the storage adapter:
without a real service-account key and folder id it stays a no-op, so dev, CI and
the current production box behave as before.

Design constraints, in order of importance:
  * logging must never break or block the application -- the queue is bounded and
    every failure is swallowed after a local warning;
  * stdout keeps receiving the same JSON, so `docker logs` stays useful whether
    or not shipping is on.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Optional

import structlog

from app.config import config

logger = structlog.get_logger()

IAM_TOKEN_URL = "https://iam.api.cloud.yandex.net/iam/v1/tokens"
INGEST_URL = "https://logging-ingester.api.cloud.yandex.net/logging/v1/write"

# Yandex accepts up to 100 entries per write; keep well inside that.
BATCH_SIZE = 50
FLUSH_INTERVAL_SEC = 5.0
# Bounded so a Cloud Logging outage costs memory, not the process.
QUEUE_MAX = 2000
# IAM tokens live 12h; refresh early so a slow exchange never blocks a flush.
TOKEN_TTL_SEC = 10 * 3600

_LEVELS = {
    "debug": "DEBUG", "info": "INFO", "warning": "WARN",
    "error": "ERROR", "critical": "FATAL", "exception": "ERROR",
}
_DUMMY = ("dev", "dummy", "changeme", "test")


def _key_file() -> Optional[Path]:
    path = Path(config.yc_service_account_key_file or "")
    return path if path.is_file() else None


def is_configured() -> bool:
    """True when a real service-account key and folder id are available."""
    folder = (config.yc_folder_id or "").strip().lower()
    if not folder or folder in _DUMMY:
        return False
    return _key_file() is not None


class YandexCloudLogSink:
    """Batches log entries and writes them to Cloud Logging."""

    def __init__(self, folder_id: str, key_path: Path):
        self.folder_id = folder_id
        self.key_path = key_path
        self.queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=QUEUE_MAX)
        self._task: Optional[asyncio.Task] = None
        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self.dropped = 0

    # --- auth ---------------------------------------------------------------

    def _sign_jwt(self) -> str:
        import jwt  # noqa: PLC0415

        key = json.loads(self.key_path.read_text(encoding="utf-8"))
        now = int(time.time())
        payload = {
            "aud": IAM_TOKEN_URL,
            "iss": key["service_account_id"],
            "iat": now,
            "exp": now + 360,
        }
        return jwt.encode(
            payload, key["private_key"], algorithm="PS256",
            headers={"kid": key["id"]},
        )

    async def _iam_token(self, client) -> Optional[str]:
        if self._token and time.time() < self._token_expires_at:
            return self._token
        try:
            res = await client.post(IAM_TOKEN_URL, json={"jwt": self._sign_jwt()}, timeout=10.0)
            res.raise_for_status()
            self._token = res.json()["iamToken"]
            self._token_expires_at = time.time() + TOKEN_TTL_SEC
            return self._token
        except Exception as e:  # noqa: BLE001
            logger.warning("YC Logging: IAM token exchange failed", error=str(e))
            self._token = None
            return None

    # --- queue --------------------------------------------------------------

    def enqueue(self, entry: dict) -> None:
        """Non-blocking; drops the entry when the queue is full."""
        try:
            self.queue.put_nowait(entry)
        except asyncio.QueueFull:
            self.dropped += 1

    async def _drain(self) -> list[dict]:
        first = await self.queue.get()
        batch = [first]
        while len(batch) < BATCH_SIZE:
            try:
                batch.append(self.queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return batch

    async def _write(self, client, batch: list[dict]) -> None:
        token = await self._iam_token(client)
        if not token:
            return
        payload = {
            "destination": {"folderId": self.folder_id},
            "entries": [
                {
                    "timestamp": e.get("timestamp"),
                    "level": _LEVELS.get(str(e.get("level", "info")).lower(), "INFO"),
                    "message": str(e.get("event", "")),
                    "jsonPayload": e,
                }
                for e in batch
            ],
        }
        try:
            res = await client.post(
                INGEST_URL, json=payload,
                headers={"Authorization": f"Bearer {token}"}, timeout=15.0,
            )
            res.raise_for_status()
        except Exception as e:  # noqa: BLE001 - never let logging break the app
            logger.warning("YC Logging: write failed", error=str(e), entries=len(batch))

    async def run(self) -> None:
        import httpx  # noqa: PLC0415

        async with httpx.AsyncClient() as client:
            while True:
                try:
                    batch = await self._drain()
                    await self._write(client, batch)
                    await asyncio.sleep(0)
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001
                    logger.warning("YC Logging: flush loop error", error=str(e))
                    await asyncio.sleep(FLUSH_INTERVAL_SEC)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.run(), name="yc-logging-sink")

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._task = None


_sink: Optional[YandexCloudLogSink] = None


def get_sink() -> Optional[YandexCloudLogSink]:
    return _sink


def yc_processor(logger_, method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """structlog processor: copy the entry to Cloud Logging, pass it through."""
    if _sink is not None:
        _sink.enqueue(dict(event_dict))
    return event_dict


def init_yc_logging() -> bool:
    """Start shipping if credentials allow. Returns whether it was enabled."""
    global _sink

    if not is_configured():
        logger.info("YC Logging disabled (no service account key / folder id)")
        return False
    key_path = _key_file()
    if key_path is None:  # pragma: no cover - is_configured already checked
        return False

    _sink = YandexCloudLogSink(config.yc_folder_id, key_path)
    _sink.start()
    logger.info("YC Logging enabled", folder_id=config.yc_folder_id)
    return True


async def shutdown_yc_logging() -> None:
    global _sink

    if _sink is not None:
        await _sink.stop()
        _sink = None
