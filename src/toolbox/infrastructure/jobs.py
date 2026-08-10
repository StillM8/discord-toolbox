"""Initial bounded in-process job runner."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from uuid import UUID, uuid4


class SimpleJobRunner:
    """Track async work and drain it during shutdown."""

    def __init__(self, *, max_concurrency: int = 4) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._tasks: dict[UUID, asyncio.Task[object]] = {}

    async def submit(self, operation: Awaitable[object]) -> UUID:
        job_id = uuid4()

        async def guarded() -> object:
            async with self._semaphore:
                return await operation

        task = asyncio.create_task(guarded(), name=f"toolbox-job-{job_id}")
        self._tasks[job_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(job_id, None))
        return job_id

    async def shutdown(self) -> None:
        tasks = tuple(self._tasks.values())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
