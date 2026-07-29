"""Structured logging setup. TZ sections 24.1 and 35.11.

JSON logs (structlog) with ISO timestamps and log level, filtered at INFO. Called
once at application startup.

The same entries are copied to Yandex Cloud Logging when a service account is
configured (app/services/yc_logging.py). Inside Yandex Cloud stdout is collected
for you; this deployment runs on a plain VPS, where nothing was.
"""
from __future__ import annotations

import logging

import structlog


def setup_logging(level: int = logging.INFO) -> None:
    from app.services.yc_logging import yc_processor

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            # Ships a copy when enabled; a no-op otherwise. Placed before the
            # renderer so it sees the event dict, not a rendered string.
            yc_processor,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
