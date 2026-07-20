"""Signal scoring batch task tests (TZ 16.1 / 11.1)."""
import pytest


@pytest.mark.asyncio
async def test_score_intent_batch_noop_without_ai():
    # Test env has no AI provider configured -> task is a safe no-op.
    from worker.tasks.signal_tasks import _score_intent_batch

    assert await _score_intent_batch() == 0


def test_as_int_helper():
    from worker.tasks.signal_tasks import _as_int

    assert _as_int(None) is None
    assert _as_int("7000000") == 7_000_000
    assert _as_int("n/a") is None
    assert _as_int(5) == 5
