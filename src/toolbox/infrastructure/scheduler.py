"""Restart-safe reminder scheduler built on durable storage plus JobRunner."""

from __future__ import annotations

import asyncio
import logging

from toolbox.core.contracts import Clock, JobRunner, ReminderDelivery, ReminderRepository
from toolbox.core.models import Reminder
from toolbox.infrastructure.logging import log_event


class ReminderScheduler:
    """Poll durable reminders and hand delivery to bounded background work."""

    def __init__(
        self,
        repository: ReminderRepository,
        delivery: ReminderDelivery,
        jobs: JobRunner,
        clock: Clock,
        *,
        interval_seconds: float = 15.0,
        batch_size: int = 20,
    ) -> None:
        self._repository = repository
        self._delivery = delivery
        self._jobs = jobs
        self._clock = clock
        self._interval_seconds = interval_seconds
        self._batch_size = batch_size
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._logger = logging.getLogger("toolbox.scheduler")

    async def tick(self) -> int:
        """Claim due rows and submit each delivery exactly once."""

        now = self._clock.now()
        reminders = await self._repository.due(now, limit=self._batch_size)
        submitted = 0
        for reminder in reminders:
            if not await self._repository.claim(reminder.reminder_id, now):
                continue
            await self._jobs.submit(self._deliver(reminder))
            submitted += 1
        return submitted

    async def start(self) -> None:
        """Start one polling task if durable reminders are enabled."""

        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="toolbox-reminder-scheduler")

    async def stop(self) -> None:
        """Stop polling without discarding durable rows."""

        self._stop.set()
        if self._task is not None:
            await self._task
            self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.tick()
            except Exception:
                log_event(
                    self._logger,
                    "reminder_scheduler_tick_failed",
                    level=logging.ERROR,
                    exc_info=True,
                )
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval_seconds)
            except TimeoutError:
                continue

    async def _deliver(self, reminder: Reminder) -> None:
        try:
            await self._delivery.deliver(reminder)
        except Exception:
            await self._repository.mark_failed(reminder.reminder_id, self._clock.now())
            log_event(
                self._logger,
                "reminder_delivery_failed",
                level=logging.ERROR,
                owner_id=reminder.owner_id,
                reminder_id=str(reminder.reminder_id),
                exc_info=True,
            )
            return
        await self._repository.mark_delivered(reminder.reminder_id)
        log_event(
            self._logger,
            "reminder_delivered",
            owner_id=reminder.owner_id,
            reminder_id=str(reminder.reminder_id),
        )
