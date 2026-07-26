"""jsat._cache.memory — In-process LRU semantic cache. Zero external deps."""
from __future__ import annotations

import time
from collections import OrderedDict


class MemoryCache:
    """LRU in-process cache. v0.1 uses exact (query, context_hash) matching."""

    def __init__(self, max_size: int = 1000, ttl_seconds: int = 3600) -> None:
        import structlog
        self._log = structlog.get_logger(__name__).bind(backend="MemoryCache")
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._store: OrderedDict[str, dict] = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._log.info("cache_init", max_size=max_size, ttl_seconds=ttl_seconds)

    @staticmethod
    def _key(query: str, context_hash: str) -> str:
        return f"{query}\x00{context_hash}"

    def _expired(self, entry: dict) -> bool:
        return time.monotonic() > entry["expires_at"]

    def get(self, query: str, context_hash: str) -> str | None:
        key = self._key(query, context_hash)
        entry = self._store.get(key)
        if entry is None:
            self._misses += 1
            return None
        if self._expired(entry):
            del self._store[key]
            self._misses += 1
            self._log.debug("cache_miss_expired", key=key[:32])
            return None
        self._store.move_to_end(key)
        self._hits += 1
        self._log.debug("cache_hit", key=key[:32])
        return entry["result"]

    def set(
        self, query: str, context_hash: str, result: str, affected_files: list[str] = None
    ) -> None:
        if affected_files is None:
            affected_files = []
        key = self._key(query, context_hash)
        expires_at = time.monotonic() + self._ttl
        if key in self._store:
            self._store[key] = {
                "result": result,
                "expires_at": expires_at,
                "affected_files": list(affected_files),
            }
            self._store.move_to_end(key)
            return
        # Evict expired entries first
        expired = [k for k, v in self._store.items() if self._expired(v)]
        for k in expired:
            del self._store[k]
        # LRU eviction if still full
        if len(self._store) >= self._max_size:
            self._store.popitem(last=False)
        self._store[key] = {
            "result": result,
            "expires_at": expires_at,
            "affected_files": list(affected_files),
        }
        self._store.move_to_end(key)
        self._log.debug("cache_set", key=key[:32], size=len(self._store))

    def invalidate_for_files(self, changed_files: list[str]) -> int:
        if not changed_files:
            return 0
        changed = set(changed_files)
        keys = [k for k, v in self._store.items() if changed.intersection(v["affected_files"])]
        for k in keys:
            del self._store[k]
        self._log.info("cache_invalidated", removed=len(keys), changed_files=list(changed))
        return len(keys)

    def clear(self) -> None:
        self._store.clear()
        self._hits = self._misses = 0
        self._log.info("cache_cleared")

    def stats(self) -> dict:
        total = self._hits + self._misses
        return {
            "size": len(self._store),
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total, 4) if total else 0.0,
        }
