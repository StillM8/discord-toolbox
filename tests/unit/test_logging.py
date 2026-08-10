from __future__ import annotations

import json
import logging

from _pytest.logging import LogCaptureFixture

from toolbox.infrastructure.logging import JsonFormatter, log_event


def test_structured_log_contains_operation_fields_without_private_content() -> None:
    record = logging.LogRecord(
        name="toolbox.discord",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="discord_interaction_completed",
        args=(),
        exc_info=None,
    )
    record.toolbox_fields = {  # type: ignore[attr-defined]
        "request_id": "request-1",
        "capability": "ping",
        "actor_id": 42,
    }

    payload = json.loads(JsonFormatter().format(record))

    assert payload["event"] == "discord_interaction_completed"
    assert payload["request_id"] == "request-1"
    assert payload["actor_id"] == 42
    assert "message_content" not in payload


def test_log_event_passes_explicit_fields_to_logger(caplog: LogCaptureFixture) -> None:
    logger = logging.getLogger("toolbox.test.logging")

    with caplog.at_level(logging.INFO, logger=logger.name):
        log_event(logger, "test_event", request_id="abc", duration_ms=12.5)

    record = caplog.records[-1]
    assert record.getMessage() == "test_event"
    assert getattr(record, "toolbox_fields") == {"request_id": "abc", "duration_ms": 12.5}
