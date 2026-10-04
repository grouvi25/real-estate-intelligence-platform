"""Structured logging setup. TZ sections 24.1 and 35.11.

JSON logs (structlog) with ISO timestamps and log level, filtered at INFO. Called
once at application startup.

Shipping those entries to Yandex Cloud Logging is not this process's job. The
deployment runs on a Yandex Cloud VM where Unified Agent (the `logs` service in
docker-compose.yml, configured by deploy/unified-agent.yml) reads the container
logs out of journald and streams them on. That covers worker, beat, db and redis
as well, and keeps working when the application itself is the thing that broke.
"""
from __future__ import annotations

import logging

import structlog


# These clients log every request URL at INFO, and our URLs carry secrets: the
# VK access_token in the query string, the bot token in api.telegram.org/bot<token>.
# The worker printed them into the container log on every collection run.
SECRET_BEARING_LOGGERS = ("httpx", "httpcore", "telethon.network")


def quiet_secret_bearing_loggers() -> None:
    for name in SECRET_BEARING_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def setup_logging(level: int = logging.INFO) -> None:
    quiet_secret_bearing_loggers()
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
