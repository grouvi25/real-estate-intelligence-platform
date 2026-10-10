"""The ten platform searchers of ТЗ «Сигналы» 2.3."""
from __future__ import annotations

from app.services.discovery.searchers.forums import ForumDiscoverer
from app.services.discovery.searchers.rss import RSSDiscoverer
from app.services.discovery.searchers.stubs import (
    ClassifiedsSearcher,
    OtzovikSearcher,
    WordstatWatcher,
)
from app.services.discovery.searchers.tg_catalog import TelegramCatalogSearcher
from app.services.discovery.searchers.telegram import TelegramSearcher
from app.services.discovery.searchers.vk_groups import VKGroupSearcher
from app.services.discovery.searchers.yandex_maps import YandexMapsSearcher
from app.services.discovery.searchers.youtube import YouTubeSearcher


def all_searchers() -> list:
    return [
        TelegramSearcher(),
        VKGroupSearcher(),
        RSSDiscoverer(),
        ClassifiedsSearcher(),
        YouTubeSearcher(),
        TelegramCatalogSearcher(),
        YandexMapsSearcher(),
        OtzovikSearcher(),
        ForumDiscoverer(),
        WordstatWatcher(),
    ]
