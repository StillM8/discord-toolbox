from __future__ import annotations

from collections.abc import Awaitable, Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from toolbox.core.models import Reminder, ReminderStatus
from toolbox.infrastructure.scheduler import ReminderScheduler


class Clock:
    def now(self) -> datetime:
        return datetime(2026, 1, 1, 12, tzinfo=UTC)


class Repository:
    def __init__(self, reminder: Reminder) -> None:
        self.reminder = reminder
        self.claimed = False
        self.status = reminder.status

    async def create(self, reminder: Reminder) -> None:
        self.reminder = reminder

    async def due(self, now: datetime, limit: int = 20) -> Sequence[Reminder]:
        del now, limit
        return (self.reminder,) if not self.claimed else ()

    async def claim(self, reminder_id: UUID, now: datetime) -> bool:
        del now
        if reminder_id != self.reminder.reminder_id or self.claimed:
            return False
        self.claimed = True
        self.status = ReminderStatus.CLAIMED
        return True

    async def mark_delivered(self, reminder_id: UUID) -> None:
        assert reminder_id == self.reminder.reminder_id
        self.status = ReminderStatus.DELIVERED

    async def mark_failed(self, reminder_id: UUID, now: datetime) -> None:
        assert reminder_id == self.reminder.reminder_id
        del now
        self.status = ReminderStatus.FAILED

    async def list_for_owner(self, owner_id: int) -> Sequence[Reminder]:
        del owner_id
        return (self.reminder,)

    async def cancel(self, owner_id: int, reminder_id: UUID) -> None:
        del owner_id, reminder_id
        self.status = ReminderStatus.CANCELLED


class Jobs:
    async def submit(self, operation: Awaitable[object]) -> UUID:
        await operation
        return uuid4()


class Delivery:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.delivered: list[Reminder] = []

    async def deliver(self, reminder: Reminder) -> None:
        if self.fail:
            raise RuntimeError("delivery failed")
        self.delivered.append(reminder)


def reminder() -> Reminder:
    return Reminder(
        reminder_id=uuid4(),
        owner_id=42,
        due_at_utc=datetime(2026, 1, 1, 11, tzinfo=UTC),
        payload="drink water",
        status=ReminderStatus.PENDING,
    )


@pytest.mark.asyncio
async def test_scheduler_claims_and_delivers_durable_reminder() -> None:
    repository = Repository(reminder())
    delivery = Delivery()
    scheduler = ReminderScheduler(repository, delivery, Jobs(), Clock())

    assert await scheduler.tick() == 1
    assert delivery.delivered[0].payload == "drink water"
    assert repository.status is ReminderStatus.DELIVERED


@pytest.mark.asyncio
async def test_scheduler_marks_failed_delivery_for_retry() -> None:
    repository = Repository(reminder())
    scheduler = ReminderScheduler(repository, Delivery(fail=True), Jobs(), Clock())

    assert await scheduler.tick() == 1
    assert repository.status is ReminderStatus.FAILED
