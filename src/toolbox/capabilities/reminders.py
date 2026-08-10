"""Owner-scoped reminder commands over durable repository state."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import dateparser

from toolbox.core.contracts import Clock, PreferencesRepository, ReminderRepository
from toolbox.core.errors import InvalidRequest
from toolbox.core.models import (
    ErrorResult,
    Reminder,
    ReminderStatus,
    TextResult,
    ToolRequest,
    ToolResult,
)


class ReminderCreateCapability:
    """Create a restart-safe reminder from explicit normalized options."""

    _relative = re.compile(r"^in\s+(?P<amount>\d+)\s*(?P<unit>minutes?|hours?|days?)$", re.I)

    def __init__(
        self,
        repository: ReminderRepository,
        clock: Clock,
        preferences: PreferencesRepository | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._preferences = preferences

    async def execute(self, request: ToolRequest) -> ToolResult:
        payload = (request.options.get("payload") or request.text or "").strip()
        due_text = request.options.get("due_at", "")
        if not payload or not due_text:
            return ErrorResult(
                code="invalid_request",
                message="Provide a reminder note and time, such as `in 30 minutes`.",
            )
        try:
            timezone = "UTC"
            if self._preferences is not None:
                timezone = (await self._preferences.get(request.actor.user.user_id)).timezone
            due_at = self._parse_due(due_text, self._clock.now(), timezone)
        except InvalidRequest as error:
            return ErrorResult(code=error.code, message="That reminder time is not valid.")
        if due_at <= self._clock.now():
            return ErrorResult(
                code="invalid_request",
                message="Reminder time must be in the future.",
            )
        reminder = Reminder(
            reminder_id=uuid4(),
            owner_id=request.actor.user.user_id,
            due_at_utc=due_at,
            payload=payload,
            status=ReminderStatus.PENDING,
        )
        await self._repository.create(reminder)
        return TextResult(
            title="Reminder set",
            text=f"{payload}\nDue: {due_at.isoformat()}\nID: `{reminder.reminder_id}`",
        )

    @classmethod
    def _parse_due(cls, value: str, now: datetime, timezone: str = "UTC") -> datetime:
        relative = cls._relative.match(value.strip())
        if relative:
            amount = int(relative.group("amount"))
            unit = relative.group("unit").lower()
            if unit.startswith("minute"):
                return now + timedelta(minutes=amount)
            if unit.startswith("hour"):
                return now + timedelta(hours=amount)
            return now + timedelta(days=amount)
        normalized = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            try:
                owner_zone = ZoneInfo(timezone)
            except ZoneInfoNotFoundError as error:
                raise InvalidRequest from error
            parsed = dateparser.parse(
                value,
                settings={
                    "RELATIVE_BASE": now.astimezone(owner_zone),
                    "TIMEZONE": timezone,
                    "RETURN_AS_TIMEZONE_AWARE": True,
                },
            )
            if parsed is None:
                raise InvalidRequest
        if parsed.tzinfo is None:
            try:
                parsed = parsed.replace(tzinfo=ZoneInfo(timezone))
            except ZoneInfoNotFoundError as error:
                raise InvalidRequest from error
        return parsed.astimezone(UTC)


class ReminderListCapability:
    """List one owner's non-cancelled durable reminders."""

    def __init__(self, repository: ReminderRepository) -> None:
        self._repository = repository

    async def execute(self, request: ToolRequest) -> ToolResult:
        reminders = await self._repository.list_for_owner(request.actor.user.user_id)
        if not reminders:
            return TextResult(title="Reminders", text="You have no active reminders.")
        lines = [
            f"`{reminder.reminder_id}` · {reminder.due_at_utc.isoformat()} · {reminder.payload}"
            for reminder in reminders
        ]
        return TextResult(title="Reminders", text="\n".join(lines))


class ReminderCancelCapability:
    """Cancel only a reminder owned by the requesting user."""

    def __init__(self, repository: ReminderRepository) -> None:
        self._repository = repository

    async def execute(self, request: ToolRequest) -> ToolResult:
        raw_id = request.options.get("reminder_id", "")
        try:
            reminder_id = UUID(raw_id)
        except ValueError:
            return ErrorResult(code="invalid_request", message="Provide a valid reminder ID.")
        await self._repository.cancel(request.actor.user.user_id, reminder_id)
        return TextResult(title="Reminder cancelled", text=f"Cancelled `{reminder_id}`.")
