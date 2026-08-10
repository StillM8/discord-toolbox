"""Discord timestamp and Unix-time conversion utilities."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from toolbox.core.actions import share_action
from toolbox.core.contracts import Clock
from toolbox.core.errors import InvalidRequest
from toolbox.core.models import ErrorResult, TextResult, ToolRequest, ToolResult


class TimestampCapability:
    """Convert Unix seconds, ISO dates, and Discord timestamp markup."""

    _discord = re.compile(r"^<t:(?P<seconds>-?\d+)(?::[tTdDfFR])?>$")

    def __init__(self, clock: Clock | None = None) -> None:
        self._clock = clock

    async def execute(self, request: ToolRequest) -> ToolResult:
        mode = request.options.get("mode", "now").strip().lower()
        value = (request.text or request.options.get("value", "")).strip()
        timezone = request.options.get("timezone", "UTC").strip() or "UTC"
        try:
            zone = ZoneInfo(timezone)
            output = self._convert(mode, value, zone)
        except (InvalidRequest, ValueError, ZoneInfoNotFoundError, OverflowError):
            error = InvalidRequest
            return ErrorResult(
                code=error.code,
                message=(
                    "Use `now`, Unix seconds, ISO dates, or Discord markup like "
                    "`<t:1700000000:F>`."
                ),
            )
        return TextResult(
            title=f"Timestamp · {mode}",
            text=output,
            input_text=value or mode,
            actions=(share_action(),),
        )

    def _convert(self, mode: str, value: str, zone: ZoneInfo) -> str:
        if mode == "now":
            moment = self._now().astimezone(zone)
        elif mode in {"unix", "discord"}:
            seconds = self._seconds(value)
            moment = datetime.fromtimestamp(seconds, UTC).astimezone(zone)
        elif mode in {"date", "iso"}:
            moment = self._parse_date(value, zone).astimezone(zone)
        else:
            raise InvalidRequest
        seconds = int(moment.timestamp())
        return (
            f"Local: {moment.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
            f"Unix: `{seconds}`\n"
            f"Discord: `<t:{seconds}:F>`\n"
            f"Relative: `<t:{seconds}:R>`"
        )

    @classmethod
    def _seconds(cls, value: str) -> int:
        match = cls._discord.fullmatch(value)
        raw = match.group("seconds") if match is not None else value
        if not re.fullmatch(r"-?\d{1,12}", raw):
            raise InvalidRequest
        return int(raw)

    @staticmethod
    def _parse_date(value: str, zone: ZoneInfo) -> datetime:
        if not value:
            raise InvalidRequest
        normalized = value.replace("Z", "+00:00")
        moment = datetime.fromisoformat(normalized)
        return moment.replace(tzinfo=zone) if moment.tzinfo is None else moment

    def _now(self) -> datetime:
        if self._clock is not None:
            current = self._clock.now()
            return current if current.tzinfo is not None else current.replace(tzinfo=UTC)
        return datetime.now(UTC)
