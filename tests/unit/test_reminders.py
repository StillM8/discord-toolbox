from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from toolbox.capabilities.reminders import ReminderCreateCapability, ReminderListCapability
from toolbox.core.models import (
    ActorContext,
    CapabilityName,
    InteractionContext,
    Reminder,
    ReminderStatus,
    TextResult,
    ToolRequest,
    UserContext,
    UserPreferences,
)


class Clock:
    def now(self) -> datetime:
        return datetime(2026, 1, 1, 12, tzinfo=UTC)


class Repository:
    def __init__(self) -> None:
        self.items: list[Reminder] = []

    async def create(self, reminder: Reminder) -> None:
        self.items.append(reminder)

    async def due(self, now: datetime, limit: int = 20) -> Sequence[Reminder]:
        del now, limit
        return tuple(self.items)

    async def claim(self, reminder_id: UUID, now: datetime) -> bool:
        del reminder_id, now
        return True

    async def mark_delivered(self, reminder_id: UUID) -> None:
        del reminder_id

    async def mark_failed(self, reminder_id: UUID, now: datetime) -> None:
        del reminder_id, now

    async def list_for_owner(self, owner_id: int) -> Sequence[Reminder]:
        return tuple(item for item in self.items if item.owner_id == owner_id)

    async def cancel(self, owner_id: int, reminder_id: UUID) -> None:
        del owner_id, reminder_id


def request(capability: CapabilityName, *, text: str = "", **options: str) -> ToolRequest:
    return ToolRequest(
        request_id=uuid4(),
        capability=capability,
        actor=ActorContext(user=UserContext(user_id=42, display_name="Tester")),
        interaction=InteractionContext(guild_id=None, channel_id=None, surface="test"),
        text=text,
        options=options,
    )


@pytest.mark.asyncio
async def test_reminder_create_persists_relative_time_as_utc() -> None:
    repository = Repository()
    result = await ReminderCreateCapability(repository, Clock()).execute(
        request(
            CapabilityName.REMINDER_CREATE,
            text="drink water",
            due_at="in 30 minutes",
            payload="drink water",
        )
    )

    assert isinstance(result, TextResult)
    assert repository.items[0].due_at_utc == datetime(2026, 1, 1, 12, 30, tzinfo=UTC)
    assert repository.items[0].status is ReminderStatus.PENDING


@pytest.mark.asyncio
async def test_reminder_list_is_owner_scoped() -> None:
    repository = Repository()
    repository.items.append(
        Reminder(
            reminder_id=uuid4(),
            owner_id=42,
            due_at_utc=datetime(2026, 1, 1, 13, tzinfo=UTC),
            payload="owned",
            status=ReminderStatus.PENDING,
        )
    )

    result = await ReminderListCapability(repository).execute(
        request(CapabilityName.REMINDER_LIST)
    )

    assert isinstance(result, TextResult)
    assert "owned" in result.text


@pytest.mark.asyncio
async def test_naive_reminder_timestamp_uses_owner_timezone() -> None:
    class Preferences:
        async def get(self, owner_id: int) -> UserPreferences:
            assert owner_id == 42
            return UserPreferences(owner_id=owner_id, timezone="Asia/Karachi")

        async def save(self, preferences: UserPreferences) -> None:
            del preferences

    repository = Repository()
    result = await ReminderCreateCapability(repository, Clock(), Preferences()).execute(
        request(
            CapabilityName.REMINDER_CREATE,
            text="meeting",
            due_at="2026-01-02T17:00:00",
            payload="meeting",
        )
    )

    assert isinstance(result, TextResult)
    assert repository.items[0].due_at_utc == datetime(2026, 1, 2, 12, tzinfo=UTC)


def test_natural_language_reminder_time_uses_relative_base_and_timezone() -> None:
    parse_due = getattr(ReminderCreateCapability, "_parse_due")
    parsed = parse_due(
        "tomorrow 4pm",
        datetime(2026, 1, 1, 12, tzinfo=UTC),
        "Asia/Karachi",
    )

    assert parsed == datetime(2026, 1, 2, 11, tzinfo=UTC)
