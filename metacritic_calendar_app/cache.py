from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Generic, TypeVar


T = TypeVar("T")


@dataclass
class CacheItem(Generic[T]):
    value: T
    expires_at: datetime


class TTLCache:
    def __init__(self, ttl_seconds: int) -> None:
        self.ttl_seconds = ttl_seconds
        self._items: dict[str, CacheItem[object]] = {}
        self._lock = Lock()

    def get(self, key: str) -> object | None:
        now = datetime.now(timezone.utc)
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            if item.expires_at <= now:
                self._items.pop(key, None)
                return None
            return item.value

    def set(self, key: str, value: object) -> None:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=self.ttl_seconds)
        with self._lock:
            self._items[key] = CacheItem(value=value, expires_at=expires_at)

    def get_or_set(self, key: str, factory: Callable[[], T]) -> T:
        cached = self.get(key)
        if cached is not None:
            return cached  # type: ignore[return-value]

        value = factory()
        self.set(key, value)
        return value
