"""Small process-local TTL cache; never a source of truth."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class _CacheEntry[T]:
    value: T
    expires_at: datetime


class TTLCache[T]:
    """Bounded enough for temporary provider/UI values."""

    def __init__(self) -> None:
        self._items: dict[str, _CacheEntry[T]] = {}

    def set(self, key: str, value: T, ttl_seconds: int) -> None:
        self._items[key] = _CacheEntry(
            value=value,
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
        )

    def get(self, key: str) -> T | None:
        item = self._items.get(key)
        if item is None:
            return None
        if item.expires_at <= datetime.now(UTC):
            self._items.pop(key, None)
            return None
        return item.value

    def delete(self, key: str) -> None:
        self._items.pop(key, None)
