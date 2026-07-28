"""One persistent event loop per worker process, shared by all Celery tasks.

Celery tasks are plain sync functions that need to await async code (asyncpg
sessions, AI calls). Calling ``asyncio.run()`` inside each task broke in two
ways on a concurrent worker:

1. ``asyncio.run()`` refuses to start while another loop runs in the same
   thread. Under the gevent pool every greenlet shares one OS thread, so any
   two overlapping tasks raised
   ``RuntimeError: asyncio.run() cannot be called from a running event loop``.
2. asyncpg connections are bound to the loop that opened them. A fresh loop per
   task meant the production ``QueuePool`` handed out connections owned by an
   already-closed loop.

Both disappear with a single long-lived loop running in a dedicated daemon
thread: tasks submit coroutines to it and block until the result is ready.
"""
from __future__ import annotations

import asyncio
import threading
from typing import Any, Coroutine, TypeVar

import structlog

logger = structlog.get_logger()

T = TypeVar("T")

# Mirrors celery_app.conf.task_time_limit. Celery's own time limit is SIGALRM
# based and therefore prefork-only, so the runner enforces the cap instead.
DEFAULT_TIMEOUT = 300

_loop: asyncio.AbstractEventLoop | None = None
_thread: threading.Thread | None = None
_lock = threading.Lock()


def _run_forever(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    loop.run_forever()


def _ensure_loop() -> asyncio.AbstractEventLoop:
    """Return the shared loop, starting its thread on first use."""
    global _loop, _thread

    if _loop is not None and not _loop.is_closed():
        return _loop

    with _lock:
        # Re-check: another thread may have started the loop while we waited.
        if _loop is not None and not _loop.is_closed():
            return _loop

        loop = asyncio.new_event_loop()
        thread = threading.Thread(
            target=_run_forever,
            args=(loop,),
            name="reip-async-runner",
            daemon=True,
        )
        thread.start()
        _loop, _thread = loop, thread
        logger.info("Async runner started")
        return loop


def run_async(coro: Coroutine[Any, Any, T], timeout: float = DEFAULT_TIMEOUT) -> T:
    """Run ``coro`` on the shared worker loop and return its result.

    Replaces ``asyncio.run()`` in task bodies. Safe to call from several Celery
    worker threads at once.
    """
    loop = _ensure_loop()

    if threading.current_thread() is _thread:
        raise RuntimeError("run_async() called from the runner loop thread; await the coroutine instead")

    future = asyncio.run_coroutine_threadsafe(coro, loop)
    try:
        return future.result(timeout=timeout)
    except TimeoutError:
        future.cancel()
        logger.error("Async task exceeded timeout", timeout=timeout)
        raise
