"""Tests for the Celery app configuration and task registration (no broker needed)."""


def _finalized_app():
    """Import task modules and finalize the app so shared_task tasks register."""
    import worker.tasks.crm_tasks  # noqa: F401
    import worker.tasks.geo_tasks  # noqa: F401
    import worker.tasks.knowledge_tasks  # noqa: F401
    import worker.tasks.maintenance_tasks  # noqa: F401
    import worker.tasks.matching_tasks  # noqa: F401
    import worker.tasks.partner_tasks  # noqa: F401
    import worker.tasks.report_tasks  # noqa: F401
    import worker.tasks.source_tasks  # noqa: F401
    from worker.celery_app import celery_app

    celery_app.finalize()
    return celery_app


def test_celery_app_config():
    from worker.celery_app import celery_app

    assert celery_app.main == "real_estate_intelligence"
    conf = celery_app.conf
    assert conf.task_serializer == "json"
    assert conf.result_serializer == "json"
    assert conf.accept_content == ["json"]
    assert conf.timezone == "Europe/Moscow"
    assert conf.task_time_limit == 300
    assert conf.worker_prefetch_multiplier == 1


def test_reset_task_registered():
    celery_app = _finalized_app()
    assert "worker.tasks.maintenance_tasks.reset_daily_ai_cost" in celery_app.tasks


def test_beat_schedule_only_has_implemented_tasks():
    celery_app = _finalized_app()
    schedule = celery_app.conf.beat_schedule
    assert "ai-cost-daily-reset" in schedule
    # Every scheduled task must be a registered task (no phantom entries).
    for entry in schedule.values():
        assert entry["task"] in celery_app.tasks
