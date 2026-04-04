"""Regional cache manager with TTL, LRU eviction, and refresh support."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any


@dataclass
class _CacheEntry:
    value: Any
    expires_at: float
    updated_at: float


class RegionalCacheManager:
    """Thread-safe regional cache with basic refresh strategy support."""

    def __init__(
        self,
        *,
        ttl_seconds: int = 3600,
        max_entries: int = 10000,
        refresh_strategy: str = "lazy",
    ):
        if ttl_seconds < 1:
            raise ValueError("ttl_seconds must be >= 1")
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        if refresh_strategy not in {"lazy", "eager"}:
            raise ValueError("refresh_strategy must be 'lazy' or 'eager'")
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self.refresh_strategy = refresh_strategy
        self._store: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._refresh_success = 0
        self._refresh_failures = 0

    def _now(self) -> float:
        return time.time()

    def _evict_if_needed(self) -> None:
        while len(self._store) > self.max_entries:
            self._store.popitem(last=False)
            self._evictions += 1

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        ttl = ttl_seconds or self.ttl_seconds
        now = self._now()
        with self._lock:
            self._store[key] = _CacheEntry(value=value, expires_at=now + ttl, updated_at=now)
            self._store.move_to_end(key)
            self._evict_if_needed()

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            if entry.expires_at <= self._now():
                self._store.pop(key, None)
                self._misses += 1
                return None
            self._store.move_to_end(key)
            self._hits += 1
            return entry.value

    def invalidate(self, key: str) -> bool:
        with self._lock:
            return self._store.pop(key, None) is not None

    def refresh(self, key: str, loader) -> Any | None:
        try:
            value = loader(key)
            self.set(key, value)
            self._refresh_success += 1
            return value
        except Exception:
            self._refresh_failures += 1
            return None

    def get_stats(self) -> dict[str, float | int]:
        with self._lock:
            total = self._hits + self._misses
            hit_rate = (self._hits / total) if total else 0.0
            return {
                "entries": len(self._store),
                "max_entries": self.max_entries,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": hit_rate,
                "evictions": self._evictions,
                "refresh_success": self._refresh_success,
                "refresh_failures": self._refresh_failures,
            }
