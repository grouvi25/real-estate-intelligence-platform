"""Request URLs with tokens in them must not reach the container log."""
import logging

import worker.celery_app  # noqa: F401 - importing the worker app quiets the loggers
from app.logging_config import SECRET_BEARING_LOGGERS


def test_http_clients_do_not_log_request_urls():
    for name in SECRET_BEARING_LOGGERS:
        assert not logging.getLogger(name).isEnabledFor(logging.INFO), name
