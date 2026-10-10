"""Discovery settings of an agency.

ТЗ кладёт их в agency_crm_config.config['discovery'], но та строка — настройки
CRM агентства (сейчас это TopNLab), и одна CRM на агентство: автопоиск там был
бы чужим. Настройки живут в agencies.settings['discovery'], ключи — как в ТЗ.
Чего нет в сохранённом — берётся из DEFAULTS, так что новые ключи появляются у
всех агентств сами.
"""
from __future__ import annotations

import copy
from typing import Any

DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "run_interval_minutes": 60,
    "max_new_sources_per_run": 10,
    "sandbox_retry_days": 7,
    "sandbox_score_activate": 70,
    "sandbox_score_sandbox": 40,
    "platform_budgets": {
        "telegram": {"enabled": True, "daily_requests": 200},
        "vk": {"enabled": True, "daily_requests": 500},
        "youtube": {"enabled": True, "daily_units": 5000},
        "rss": {"enabled": True},
        "forum": {"enabled": True},
        "yandex_maps": {"enabled": True},
        "wordstat": {"enabled": True},
        "tg_catalog": {"enabled": True},
        "classifieds": {"enabled": False},
        "otzovik": {"enabled": False},
    },
}

INT_LIMITS = {
    "run_interval_minutes": (60, 7 * 24 * 60),
    "max_new_sources_per_run": (1, 50),
    "sandbox_retry_days": (1, 90),
    "sandbox_score_activate": (1, 100),
    "sandbox_score_sandbox": (0, 99),
}


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def discovery_settings(agency) -> dict:
    return _merge(DEFAULTS, ((getattr(agency, "settings", None) or {}).get("discovery") or {}))


def apply_patch(agency, patch: dict) -> dict:
    """Validate and store a partial update. Raises ValueError with a Russian
    message the API hands to the owner as is."""
    current = discovery_settings(agency)
    for key, value in (patch or {}).items():
        if key == "enabled":
            current["enabled"] = bool(value)
        elif key in INT_LIMITS:
            lo, hi = INT_LIMITS[key]
            try:
                number = int(value)
            except (TypeError, ValueError):
                raise ValueError(f"{key}: ожидается число") from None
            if not lo <= number <= hi:
                raise ValueError(f"{key}: допустимо от {lo} до {hi}")
            current[key] = number
        elif key == "platform_budgets":
            if not isinstance(value, dict):
                raise ValueError("platform_budgets: ожидается объект")
            for platform, conf in value.items():
                if platform not in DEFAULTS["platform_budgets"] or not isinstance(conf, dict):
                    raise ValueError(f"Неизвестная площадка: {platform}")
                slot = current["platform_budgets"][platform]
                for k, v in conf.items():
                    if k == "enabled":
                        slot["enabled"] = bool(v)
                    elif k in ("daily_requests", "daily_units"):
                        if not isinstance(v, int) or v < 0:
                            raise ValueError(f"{platform}.{k}: ожидается целое ≥ 0")
                        slot[k] = v
                    else:
                        raise ValueError(f"{platform}: неизвестный параметр {k}")
        else:
            raise ValueError(f"Неизвестный параметр: {key}")
    if current["sandbox_score_sandbox"] >= current["sandbox_score_activate"]:
        raise ValueError("Порог песочницы должен быть ниже порога включения")
    settings = dict(getattr(agency, "settings", None) or {})
    settings["discovery"] = current
    agency.settings = settings  # new dict: JSONB changes are only seen on assignment
    return current


def platform_enabled(cfg: dict, platform: str) -> bool:
    return bool((cfg.get("platform_budgets") or {}).get(platform, {}).get("enabled", False))


# Competitors: the owner's own list plus what discovery found on Yandex Maps.
MANUAL_COMPETITORS_KEY = "competitor_names"
AUTO_COMPETITORS_KEY = "discovery_competitors"


def competitor_names_of(agency) -> list[str]:
    settings = getattr(agency, "settings", None) or {}
    seen: set[str] = set()
    out = []
    for name in list(settings.get(MANUAL_COMPETITORS_KEY) or []) + list(
            settings.get(AUTO_COMPETITORS_KEY) or []):
        key = str(name).strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(str(name).strip())
    return out
