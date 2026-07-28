"""Regression tests for worker.async_runner.

The production worker used to call asyncio.run() inside every task. On a
concurrent pool that raised "asyncio.run() cannot be called from a running event
loop" for roughly two out of three scheduled tasks, and it also handed asyncpg
connections between different event loops. These tests pin the fixed behaviour:
one shared loop, safe to drive from several threads at once.
"""
from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from worker.async_runner import run_async


async def _echo(value, delay: float = 0):
    if delay:
        await asyncio.sleep(delay)
    return value


def test_returns_coroutine_result():
    assert run_async(_echo("ok")) == "ok"


def test_propagates_exception():
    async def boom():
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        run_async(boom())


def test_concurrent_calls_from_many_threads():
    """The gevent-pool failure mode: overlapping tasks on one worker."""
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(run_async, _echo(i, delay=0.05)) for i in range(24)]
        assert sorted(f.result(timeout=30) for f in futures) == list(range(24))


def test_uses_a_single_shared_loop():
    """All tasks must land on the same loop, so pooled connections stay valid."""
    async def current_loop_id():
        return id(asyncio.get_running_loop())

    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = {f.result(timeout=30) for f in
               [pool.submit(run_async, current_loop_id()) for _ in range(8)]}
    assert len(ids) == 1


def test_loop_survives_between_calls():
    first = run_async(_echo(1))
    second = run_async(_echo(2))
    assert (first, second) == (1, 2)


def test_runner_thread_is_not_the_caller():
    async def runner_thread_name():
        return threading.current_thread().name

    assert run_async(runner_thread_name()) == "reip-async-runner"
    assert threading.current_thread().name != "reip-async-runner"


def test_timeout_raises():
    with pytest.raises(TimeoutError):
        run_async(_echo("slow", delay=5), timeout=0.1)
