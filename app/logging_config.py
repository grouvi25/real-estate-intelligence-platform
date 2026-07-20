"""Structured logging setup. TZ section 24.1.

JSON logs (structlog) with ISO timestamps and log level, filtered at INFO. Called
once at application startup.
"""
from __future__ import annotations

import logging

import structlog


def setup_logging(level: int = logging.INFO) -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
