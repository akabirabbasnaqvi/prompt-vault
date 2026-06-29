"""
app/core/logging_config.py

Structured JSON logging configuration.

SKILL: Structured logging, JSON log formatting, production observability

This module configures the entire Python logging system to output
structured JSON instead of plain text.

WHY JSON LOGS:
  Plain text: "2026-06-28 INFO app.main Creating workspace"
  JSON:       {"timestamp": "...", "level": "INFO", "request_id": "...",
               "message": "Creating workspace", "duration_ms": 12.4}

  JSON logs can be:
  - Searched by any field (request_id, level, duration)
  - Filtered in log aggregators (Datadog, CloudWatch, Elasticsearch)
  - Parsed by automated alerting systems
  - Aggregated into dashboards and metrics

In production, these JSON logs go to a log aggregation service.
Locally, they print to stdout (where Docker captures them).
"""

import logging
import sys
from pythonjsonlogger import jsonlogger
from app.core.config import settings


class PromptVaultJsonFormatter(jsonlogger.JsonFormatter):
    """
    Custom JSON formatter that adds standard fields to every log record.

    Every log line will include:
      timestamp   → ISO 8601 format
      level       → DEBUG, INFO, WARNING, ERROR, CRITICAL
      logger      → module path (e.g. "app.services.workspace_service")
      message     → the log message
      service     → always "PromptVault" (useful in multi-service systems)
      environment → "development" or "production"

    Plus any extra fields passed to the logger:
      request_id  → added by middleware
      duration_ms → added by middleware
      user_id     → can be added by auth middleware later
    """

    def add_fields(self, log_record: dict, record: logging.LogRecord, message_dict: dict) -> None:
        super().add_fields(log_record, record, message_dict)

        # Rename fields to match standard log format
        log_record["timestamp"] = log_record.pop("asctime", None)
        log_record["level"] = log_record.pop("levelname", record.levelname)
        log_record["logger"] = log_record.pop("name", record.name)

        # Add service context to every log line
        log_record["service"] = settings.app_name
        log_record["version"] = settings.app_version
        log_record["environment"] = "development" if settings.debug else "production"

        # Remove fields we do not want cluttering the output
        log_record.pop("exc_info", None)
        log_record.pop("exc_text", None)


def configure_logging() -> None:
    """
    Configure the root logger to output structured JSON.

    Call this once at application startup (in main.py).
    After this call, ALL loggers throughout the app (including
    SQLAlchemy, uvicorn, celery) output structured JSON.

    In development (DEBUG=true): pretty readable with colors still visible
    In production (DEBUG=false): pure JSON, one line per record
    """

    # ── JSON FORMATTER ────────────────────────────────────────────────
    # fmt string defines which fields appear and in what order
    # %(asctime)s    → timestamp
    # %(levelname)s  → log level
    # %(name)s       → logger name (module path)
    # %(message)s    → the actual message
    formatter = PromptVaultJsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    # ── STDOUT HANDLER ────────────────────────────────────────────────
    # All logs go to stdout.
    # Docker captures stdout and makes it available via `docker logs`.
    # Log aggregators (Datadog, CloudWatch) collect from stdout.
    # This is the standard pattern — never write to files in containers.
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    # ── ROOT LOGGER ───────────────────────────────────────────────────
    # Configuring the root logger affects ALL loggers in the application.
    # Every call to logging.getLogger(__name__) inherits this config.
    root_logger = logging.getLogger()
    root_logger.handlers.clear()    # Remove any existing handlers
    root_logger.addHandler(handler)
    root_logger.setLevel(
        logging.DEBUG if settings.debug else logging.INFO
    )

    # ── SILENCE NOISY THIRD-PARTY LOGGERS ────────────────────────────
    # Some libraries log excessively at DEBUG level.
    # We silence them to keep our logs clean.
    # Set to WARNING so only important messages from these libs appear.
    noisy_loggers = [
        "sqlalchemy.engine",        # SQL query logging (very verbose)
        "sqlalchemy.pool",          # Connection pool events
        "sqlalchemy.dialects",      # Driver-level events
        "asyncio",                  # Event loop internals
        "multiprocessing",          # Process management
        "watchfiles",               # File watching (dev mode)
        "uvicorn.access",           # Per-request access log (we do this ourselves)
    ]

    for logger_name in noisy_loggers:
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    # Always silence SQLAlchemy — we have our own request logging
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)