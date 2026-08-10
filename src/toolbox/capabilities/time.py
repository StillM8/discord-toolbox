"""Friendly, deterministic timezone conversion and current-time lookup."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from toolbox.core.actions import share_action
from toolbox.core.contracts import Clock
from toolbox.core.errors import InvalidRequest
from toolbox.core.models import ErrorResult, TextResult, ToolRequest, ToolResult


@dataclass(frozen=True, slots=True)
class _Place:
    label: str
    zone: ZoneInfo


class TimeConversionCapability:
    """Handle friendly place names as well as explicit IANA timezone names."""

    _clock_pattern = re.compile(
        r"^(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*"
        r"(?P<period>am|pm)?(?:\s+|$)",
        re.IGNORECASE,
    )
    _prefixes = (
        "what time is it in ",
        "what is the time in ",
        "current time in ",
        "time in ",
        "now in ",
    )
    _aliases: dict[str, tuple[str, str]] = {
        "uk": ("UK", "Europe/London"),
        "united kingdom": ("UK", "Europe/London"),
        "england": ("England", "Europe/London"),
        "britain": ("Britain", "Europe/London"),
        "great britain": ("Great Britain", "Europe/London"),
        "gb": ("UK", "Europe/London"),
        "london": ("London", "Europe/London"),
        "bradford": ("Bradford", "Europe/London"),
        "bradfort": ("Bradford", "Europe/London"),
        "pakistan": ("Pakistan", "Asia/Karachi"),
        "paksitan": ("Pakistan", "Asia/Karachi"),
        "pk": ("Pakistan", "Asia/Karachi"),
        "islamabad": ("Islamabad", "Asia/Karachi"),
        "karachi": ("Karachi", "Asia/Karachi"),
        "lahore": ("Lahore", "Asia/Karachi"),
        "rawalpindi": ("Rawalpindi", "Asia/Karachi"),
        "peshawar": ("Peshawar", "Asia/Karachi"),
        "quetta": ("Quetta", "Asia/Karachi"),
        "multan": ("Multan", "Asia/Karachi"),
        "dubai": ("Dubai", "Asia/Dubai"),
        "uae": ("UAE", "Asia/Dubai"),
        "india": ("India", "Asia/Kolkata"),
        "delhi": ("Delhi", "Asia/Kolkata"),
        "mumbai": ("Mumbai", "Asia/Kolkata"),
        "new york": ("New York", "America/New_York"),
        "nyc": ("New York", "America/New_York"),
        "los angeles": ("Los Angeles", "America/Los_Angeles"),
        "la": ("Los Angeles", "America/Los_Angeles"),
        "toronto": ("Toronto", "America/Toronto"),
        "tokyo": ("Tokyo", "Asia/Tokyo"),
        "sydney": ("Sydney", "Australia/Sydney"),
        "utc": ("UTC", "UTC"),
        "gmt": ("GMT", "Etc/GMT"),
    }
    _alias_tokens = tuple(
        sorted(
            [(alias.split(), alias) for alias in _aliases],
            key=lambda item: len(item[0]),
            reverse=True,
        )
    )

    def __init__(self, clock: Clock | None = None) -> None:
        self._clock = clock

    async def execute(self, request: ToolRequest) -> ToolResult:
        expression = (request.text or request.options.get("expression", "")).strip()
        try:
            places, local_time = self._parse(expression)
            if local_time is None:
                text = self._current_time_text(places)
                title = "Current time"
            else:
                if len(places) != 2:
                    raise InvalidRequest
                text = self._conversion_text(places[0], places[1], local_time)
                title = "Time conversion"
        except (InvalidRequest, ValueError, ZoneInfoNotFoundError):
            error = InvalidRequest
            return ErrorResult(
                code=error.code,
                message=(
                    "Try `UK Islamabad`, `bradfort paksitan`, or "
                    "`5pm Europe/London Asia/Karachi`."
                ),
            )
        return TextResult(
            title=title,
            text=text,
            input_text=expression,
            actions=(share_action(),),
        )

    def _current_time_text(self, places: tuple[_Place, ...]) -> str:
        now = self._now()
        return "\n".join(
            f"{place.label}: {now.astimezone(place.zone).strftime('%Y-%m-%d %H:%M %Z')}"
            for place in places
        )

    def _conversion_text(self, source: _Place, target: _Place, local_time: time) -> str:
        source_date = self._now().astimezone(source.zone).date()
        source_value = datetime.combine(source_date, local_time, tzinfo=source.zone)
        target_value = source_value.astimezone(target.zone)
        return (
            f"{source_value.strftime('%Y-%m-%d %H:%M %Z')} ({source.label})\n"
            f"→ {target_value.strftime('%Y-%m-%d %H:%M %Z')} ({target.label})"
        )

    def _now(self) -> datetime:
        if self._clock is not None:
            value = self._clock.now()
            return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return datetime.now(UTC)

    @classmethod
    def _parse(cls, expression: str) -> tuple[tuple[_Place, ...], time | None]:
        normalized = cls._strip_prefix(expression)
        local_time, remaining = cls._parse_clock_prefix(normalized)
        places = cls._parse_places(remaining)
        if not places or (local_time is not None and len(places) != 2):
            raise InvalidRequest
        return places, local_time

    @classmethod
    def _strip_prefix(cls, expression: str) -> str:
        normalized = re.sub(r"[|,]+", " ", expression.strip())
        for prefix in cls._prefixes:
            if normalized.lower().startswith(prefix):
                return normalized[len(prefix) :].strip()
        return normalized

    @classmethod
    def _parse_clock_prefix(cls, expression: str) -> tuple[time | None, str]:
        match = cls._clock_pattern.match(expression)
        if match is None:
            return None, expression
        hour = int(match.group("hour"))
        minute = int(match.group("minute") or "0")
        period = match.group("period")
        if period:
            if hour < 1 or hour > 12:
                raise InvalidRequest
            if period.lower() == "pm" and hour != 12:
                hour += 12
            if period.lower() == "am" and hour == 12:
                hour = 0
        if hour > 23 or minute > 59:
            raise InvalidRequest
        return time(hour, minute), expression[match.end() :].strip()

    @classmethod
    def _parse_places(cls, expression: str) -> tuple[_Place, ...]:
        ignored = {"to", "and", "between", "from", "in", "at"}
        raw_tokens = expression.split()
        tokens = [token.lower() for token in raw_tokens if token.lower() not in ignored]
        raw_tokens = [token for token in raw_tokens if token.lower() not in ignored]
        places: list[_Place] = []
        index = 0
        while index < len(tokens):
            matched: tuple[str, str] | None = None
            consumed = 0
            for alias_tokens, alias in cls._alias_tokens:
                if tokens[index : index + len(alias_tokens)] == alias_tokens:
                    matched = cls._aliases[alias]
                    consumed = len(alias_tokens)
                    break
            if matched is not None:
                label, zone_name = matched
                places.append(_Place(label, ZoneInfo(zone_name)))
                index += consumed
                continue
            token = tokens[index]
            if "/" not in token:
                raise InvalidRequest
            zone_name = raw_tokens[index]
            places.append(_Place(zone_name, ZoneInfo(zone_name)))
            index += 1
        if len(places) > 4:
            raise InvalidRequest
        return tuple(places)
