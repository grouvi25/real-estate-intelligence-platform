"""Guard test: list_signals must use plain defaults (directly callable, no Query markers)."""
import inspect


def test_list_signals_defaults_are_plain_values():
    from app.routers.signals import list_signals

    params = inspect.signature(list_signals).parameters
    assert params["limit"].default == 50
    assert params["offset"].default == 0
    assert params["status"].default is None
    assert params["urgency"].default is None
    assert params["min_intent_score"].default is None
    assert params["geo_id"].default is None
