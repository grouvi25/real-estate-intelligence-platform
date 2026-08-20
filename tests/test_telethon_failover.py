"""Очередь аккаунтов Telegram: упал основной — работает резервный.

Аккаунт для сбора расходный, его блокируют. До появления очереди это означало
полную остановку Telegram-сбора до тех пор, пока человек не дойдёт до сервера.
Проверяется здесь именно граница: когда переключаемся, когда останавливаемся и
что заблокированный аккаунт больше не берут в работу.
"""
import os

import pytest

from app.collectors import telethon_sessions
from app.config import config

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DB_TESTS") != "1", reason="requires live Redis")


@pytest.fixture(autouse=True)
async def _clean():
    await telethon_sessions.revive()
    yield
    await telethon_sessions.revive()


def _two(monkeypatch):
    monkeypatch.setattr(config, "telethon_sessions_raw", "main_acc, backup_acc")


@pytest.mark.asyncio
async def test_queue_reads_the_list_in_order(monkeypatch):
    _two(monkeypatch)
    assert telethon_sessions.sessions() == ["main_acc", "backup_acc"]


@pytest.mark.asyncio
async def test_one_name_twice_is_not_a_spare(monkeypatch):
    """Дубль в списке — не резерв: сбор дважды упал бы на одном аккаунте."""
    monkeypatch.setattr(config, "telethon_sessions_raw", "main_acc,main_acc")
    assert telethon_sessions.sessions() == ["main_acc"]


@pytest.mark.asyncio
async def test_empty_list_falls_back_to_the_single_session(monkeypatch):
    monkeypatch.setattr(config, "telethon_sessions_raw", "")
    monkeypatch.setattr(config, "telethon_session_name", "solo_acc")
    assert telethon_sessions.sessions() == ["solo_acc"]


@pytest.mark.asyncio
async def test_dead_account_hands_work_to_the_spare(monkeypatch):
    _two(monkeypatch)
    assert await telethon_sessions.active_session() == "main_acc"

    await telethon_sessions.mark_dead("main_acc", "SessionRevokedError")

    assert await telethon_sessions.active_session() == "backup_acc"
    assert await telethon_sessions.alive_sessions() == ["backup_acc"]


@pytest.mark.asyncio
async def test_when_every_account_is_gone_there_is_nothing_to_work_with(monkeypatch):
    _two(monkeypatch)
    await telethon_sessions.mark_dead("main_acc", "revoked")
    await telethon_sessions.mark_dead("backup_acc", "revoked")

    assert await telethon_sessions.active_session() is None
    assert await telethon_sessions.alive_sessions() == []


@pytest.mark.asyncio
async def test_reviving_brings_the_queue_back(monkeypatch):
    _two(monkeypatch)
    await telethon_sessions.mark_dead("main_acc", "revoked")
    assert await telethon_sessions.revive("main_acc") == 1
    assert await telethon_sessions.active_session() == "main_acc"


@pytest.mark.asyncio
async def test_switch_hands_over_and_says_work_continues(monkeypatch):
    """_switch_or_pause отвечает на единственный важный вопрос: есть ли кем дальше."""
    from worker.tasks import collector_tasks

    _two(monkeypatch)
    sent: list[str] = []

    async def _capture(text: str) -> bool:
        sent.append(text)
        return True

    monkeypatch.setattr("app.services.alerts.send_critical_alert", _capture)

    switched = await collector_tasks._switch_or_pause("main_acc", RuntimeError("revoked"))

    assert switched is True
    assert await telethon_sessions.active_session() == "backup_acc"
    assert sent and "резервным" in sent[0]


@pytest.mark.asyncio
async def test_switch_says_stop_when_the_last_account_is_gone(monkeypatch):
    from worker.tasks import collector_tasks

    _two(monkeypatch)
    await telethon_sessions.mark_dead("backup_acc", "revoked")

    async def _capture(text: str) -> bool:
        return True

    monkeypatch.setattr("app.services.alerts.send_critical_alert", _capture)

    switched = await collector_tasks._switch_or_pause("main_acc", RuntimeError("revoked"))
    assert switched is False
