"""Avito & CIAN classifieds adapters. Signal Bus addendum.

These platforms actively block automated posting, so replies are not delivered
automatically (reply_supported=False); the Signal Bus surfaces a draft for the
manager to send manually. Ingestion normalizes an item payload (obtained via the
platform's own export/API where the agency is authorized).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import structlog

from app.config import config
from app.services.channels.base import ChannelAdapter, NormalizedContent, author_hash

logger = structlog.get_logger()


def _parse_ts(value: object) -> Optional[datetime]:
    if not value:
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, OSError):
        return None


class _ClassifiedAdapter(ChannelAdapter):
    def normalize(self, raw: dict) -> NormalizedContent:
        author_id = raw.get("user_id") or raw.get("author_id")
        title = raw.get("title") or ""
        description = raw.get("description") or raw.get("text") or ""
        content = f"{title}\n{description}".strip()
        return NormalizedContent(
            channel=self.channel,
            external_id=str(raw["id"]) if raw.get("id") is not None else None,
            url=raw.get("url"),
            content_type=raw.get("content_type", "listing"),
            raw_content=content,
            author_hash=author_hash(self.channel, author_id),
            author_display_name=raw.get("author_name"),
            published_at=_parse_ts(raw.get("published_at") or raw.get("time")),
            meta={k: raw[k] for k in ("price", "address", "category") if k in raw},
        )


    @property
    def api_base_url(self) -> Optional[str]:
        return getattr(config, self.base_url_setting)

    @property
    def api_token(self) -> Optional[str]:
        return getattr(config, self.token_setting)

    def reply_supported(self) -> bool:
        return bool(self.api_base_url and self.api_token)

    async def send_reply(self, target: str, text: str) -> dict:
        """Use the accredited official API, otherwise fail closed with guidance.

        The addendum's acceptance list asks these adapters to block sending "с
        понятной ошибкой в логах" when the agency has no professional account.
        Falling through to the generic "reply_not_supported" left the signal
        marked skipped with nothing said about why or what to do.
        """
        if self.reply_supported():
            import httpx
            url = f"{self.api_base_url.rstrip('/')}/messages/{target}"
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    response = await client.post(
                        url,
                        json={"message": text},
                        headers={"Authorization": f"Bearer {self.api_token}"},
                    )
                ok = response.status_code < 400
                if not ok:
                    logger.warning("Classified reply rejected", channel=self.channel,
                                   status=response.status_code)
                return {"sent": ok, "channel": self.channel,
                        "status_code": response.status_code}
            except Exception as exc:
                logger.warning("Classified reply failed", channel=self.channel, error=str(exc))
                return {"sent": False, "reason": "transport_error", "channel": self.channel}

        logger.warning(
            "%s: ответ не отправлен — нужен профессиональный кабинет площадки "
            "и доступ к её API; черновик сохранён для ручной отправки",
            self.channel, extra={"channel": self.channel},
        )
        return {
            "sent": False,
            "reason": "account_required",
            "channel": self.channel,
            "detail": (f"{self.title} требует профессионального кабинета агентства "
                       "и доступа к API. Черновик сохранён — отправьте вручную."),
        }


class AvitoAdapter(_ClassifiedAdapter):
    channel = "avito"
    title = "Avito"
    base_url_setting = "avito_api_base_url"
    token_setting = "avito_api_token"


class CianAdapter(_ClassifiedAdapter):
    channel = "cian"
    base_url_setting = "cian_api_base_url"
    token_setting = "cian_api_token"
    title = "ЦИАН"
