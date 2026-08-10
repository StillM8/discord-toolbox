"""Time sources for expiry and scheduling."""

from __future__ import annotations

from datetime import UTC, datetime


class SystemClock:
    """Production UTC clock."""

    def now(self) -> datetime:
        return datetime.now(UTC)
