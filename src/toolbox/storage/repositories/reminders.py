"""SQL durable reminder repository."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import case, select, update

from toolbox.core.contracts import ReminderRepository
from toolbox.core.models import Reminder, ReminderStatus
from toolbox.storage.database import Database
from toolbox.storage.models import ReminderRow, as_utc


class SQLReminderRepository(ReminderRepository):
    """Claim reminders atomically so restart/retry does not duplicate work."""

    def __init__(
        self,
        database: Database,
        *,
        max_attempts: int = 3,
        claim_timeout_seconds: int = 120,
    ) -> None:
        self._database = database
        self._max_attempts = max(1, max_attempts)
        self._claim_timeout = timedelta(seconds=max(1, claim_timeout_seconds))

    async def create(self, reminder: Reminder) -> None:
        async with self._database.sessions() as session:
            session.add(
                ReminderRow(
                    id=str(reminder.reminder_id),
                    owner_id=reminder.owner_id,
                    due_at_utc=reminder.due_at_utc,
                    payload=reminder.payload,
                    status=reminder.status.value,
                    attempt_count=reminder.attempt_count,
                    claimed_at=reminder.claimed_at,
                )
            )
            await session.commit()

    async def due(self, now: datetime, limit: int = 20) -> tuple[Reminder, ...]:
        async with self._database.sessions() as session:
            result = await session.execute(
                select(ReminderRow)
                .where(
                    ReminderRow.due_at_utc <= now,
                    ReminderRow.status.in_(
                        [ReminderStatus.PENDING.value, ReminderStatus.FAILED.value]
                    )
                    | (
                        (ReminderRow.status == ReminderStatus.CLAIMED.value)
                        & (ReminderRow.claimed_at <= now - self._claim_timeout)
                    ),
                    ReminderRow.attempt_count < self._max_attempts,
                )
                .order_by(ReminderRow.due_at_utc.asc())
                .limit(limit)
            )
            return tuple(self._to_reminder(row) for row in result.scalars())

    async def claim(self, reminder_id: UUID, now: datetime) -> bool:
        async with self._database.sessions() as session:
            result = await session.execute(
                update(ReminderRow)
                .where(
                    ReminderRow.id == str(reminder_id),
                    ReminderRow.status.in_(
                        [ReminderStatus.PENDING.value, ReminderStatus.FAILED.value]
                    )
                    | (
                        (ReminderRow.status == ReminderStatus.CLAIMED.value)
                        & (ReminderRow.claimed_at <= now - self._claim_timeout)
                    ),
                    ReminderRow.attempt_count < self._max_attempts,
                    ReminderRow.due_at_utc <= now,
                )
                .values(
                    status=ReminderStatus.CLAIMED.value,
                    claimed_at=now,
                    last_attempt_at=now,
                    attempt_count=ReminderRow.attempt_count + 1,
                )
            )
            await session.commit()
            return getattr(result, "rowcount", 0) == 1

    async def mark_delivered(self, reminder_id: UUID) -> None:
        await self._set_status(reminder_id, ReminderStatus.DELIVERED)

    async def mark_failed(self, reminder_id: UUID, now: datetime) -> None:
        async with self._database.sessions() as session:
            await session.execute(
                update(ReminderRow)
                .where(ReminderRow.id == str(reminder_id))
                .values(
                    status=case(
                        (
                            ReminderRow.attempt_count >= self._max_attempts,
                            ReminderStatus.CANCELLED.value,
                        ),
                        else_=ReminderStatus.FAILED.value,
                    ),
                    claimed_at=None,
                    due_at_utc=now,
                )
            )
            await session.commit()

    async def list_for_owner(self, owner_id: int) -> tuple[Reminder, ...]:
        async with self._database.sessions() as session:
            result = await session.execute(
                select(ReminderRow)
                .where(
                    ReminderRow.owner_id == owner_id,
                    ReminderRow.status != ReminderStatus.CANCELLED.value,
                )
                .order_by(ReminderRow.due_at_utc.asc())
            )
            return tuple(self._to_reminder(row) for row in result.scalars())

    async def cancel(self, owner_id: int, reminder_id: UUID) -> None:
        async with self._database.sessions() as session:
            await session.execute(
                update(ReminderRow)
                .where(
                    ReminderRow.id == str(reminder_id),
                    ReminderRow.owner_id == owner_id,
                )
                .values(status=ReminderStatus.CANCELLED.value, claimed_at=None)
            )
            await session.commit()

    async def _set_status(self, reminder_id: UUID, status: ReminderStatus) -> None:
        async with self._database.sessions() as session:
            await session.execute(
                update(ReminderRow)
                .where(ReminderRow.id == str(reminder_id))
                .values(status=status.value, claimed_at=None)
            )
            await session.commit()

    @staticmethod
    def _to_reminder(row: ReminderRow) -> Reminder:
        return Reminder(
            reminder_id=UUID(row.id),
            owner_id=row.owner_id,
            due_at_utc=as_utc(row.due_at_utc),
            payload=row.payload,
            status=ReminderStatus(row.status),
            attempt_count=row.attempt_count,
            claimed_at=as_utc(row.claimed_at) if row.claimed_at else None,
        )
