"""Structured logging used by the application and Discord adapter."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, cast


class JsonFormatter(logging.Formatter):
    """Render log records as compact JSON without serializing private content."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }

        fields = getattr(record, "toolbox_fields", None)
        if isinstance(fields, dict):
            payload.update(cast(dict[str, object], fields))

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str, separators=(",", ":"))


def log_event(
    logger: logging.Logger,
    event: str,
    *,
    level: int = logging.INFO,
    exc_info: bool | tuple[type[BaseException], BaseException, TracebackType | None] = False,
    **fields: object,
) -> None:
    """Emit a structured event with only explicitly selected fields."""

    logger.log(
        level,
        event,
        extra={"toolbox_fields": fields},
        exc_info=exc_info,
    )


def configure_logging(level: str = "INFO") -> None:
    """Configure application and Discord library logs once at startup."""

    root = logging.getLogger()
    root.setLevel(level.upper())

    for handler in root.handlers:
        if getattr(handler, "_toolbox_handler", False):
            return

    handler = logging.StreamHandler(sys.stdout)
    handler._toolbox_handler = True  # type: ignore[attr-defined]
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)

    # Gateway-level diagnostics are useful; HTTP client debug payloads are not.
    logging.getLogger("discord").setLevel(logging.INFO)
    logging.getLogger("discord.http").setLevel(logging.WARNING)
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
