"""Lightweight in-memory TTL cache.

Username ownership and Fragment listing state can change at any time, so
results are cached only briefly (default 5 minutes). Errors are cached for a
shorter period than successful results. The cache is process-local, which is
safe and sufficient for serverless deployments (worst case: a few duplicate
upstream lookups across concurrent cold instances).
"""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Generic, Optional, TypeVar

T = TypeVar("T")


class TTLCache(Generic[T]):
    def __init__(self, ttl_seconds: int, max_entries: int = 2048) -> None:
        self._ttl = ttl_seconds
        self._max = max_entries
        self._items: "OrderedDict[str, tuple[float, float, T]]" = OrderedDict()

    def get(self, key: str) -> Optional[tuple[T, float]]:
        """Return (value, age_seconds) when present and fresh, else None."""
        if self._ttl <= 0:
            return None
        entry = self._items.get(key)
        if entry is None:
            return None
        stored_at, ttl, value = entry
        age = time.monotonic() - stored_at
        if age > ttl:
            self._items.pop(key, None)
            return None
        self._items.move_to_end(key)
        return value, age

    def set(self, key: str, value: T, ttl: Optional[int] = None) -> None:
        if self._ttl <= 0:
            return
        self._items[key] = (time.monotonic(), float(ttl if ttl is not None else self._ttl), value)
        self._items.move_to_end(key)
        while len(self._items) > self._max:
            self._items.popitem(last=False)

    def clear(self) -> None:
        self._items.clear()

    @property
    def size(self) -> int:
        return len(self._items)
