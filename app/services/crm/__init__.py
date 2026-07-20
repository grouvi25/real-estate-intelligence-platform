"""CRM adapter registry. Signal Bus addendum.

build_crm_adapter(config) instantiates the right vendor adapter from an
AgencyCRMConfig row (or the equivalent kwargs). Unknown crm_type -> None.
"""
from __future__ import annotations

from typing import Optional

from app.services.crm.adapters import (
    AmoCrmAdapter,
    Bitrix24Adapter,
    TopnlabAdapter,
    YUcrmAdapter,
)
from app.services.crm.base import CRMAdapter

_ADAPTER_TYPES: dict[str, type[CRMAdapter]] = {
    "topnlab": TopnlabAdapter,
    "amocrm": AmoCrmAdapter,
    "bitrix24": Bitrix24Adapter,
    "yucrm": YUcrmAdapter,
}

SUPPORTED_CRMS = tuple(_ADAPTER_TYPES.keys())


def build_crm_adapter(
    crm_type: str,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    config: Optional[dict] = None,
    field_mapping: Optional[dict] = None,
) -> Optional[CRMAdapter]:
    cls = _ADAPTER_TYPES.get((crm_type or "").lower())
    if cls is None:
        return None
    return cls(base_url=base_url, api_key=api_key, config=config, field_mapping=field_mapping)


def adapter_from_config(cfg) -> Optional[CRMAdapter]:
    """Build an adapter from an AgencyCRMConfig ORM row."""
    return build_crm_adapter(
        cfg.crm_type, base_url=cfg.base_url, api_key=cfg.api_key,
        config=cfg.config, field_mapping=cfg.field_mapping,
    )


__all__ = [
    "CRMAdapter",
    "build_crm_adapter",
    "adapter_from_config",
    "SUPPORTED_CRMS",
]
