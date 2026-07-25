"""jsat._cache — Cache backend factory."""
from __future__ import annotations

from typing import Any


def get_cache(cfg: Any):
    backend = getattr(cfg.cache, "backend", "memory")
    if backend == "redis":
        try:
            from jsat._cache.redis import RedisCache
            return RedisCache(cfg.cache.redis_uri, cfg.cache.ttl_seconds)
        except ImportError:
            pass
    if backend == "disk":
        from jsat._cache.disk import DiskCache
        return DiskCache(cfg.cache.disk_path, cfg.cache.ttl_seconds)
    from jsat._cache.memory import MemoryCache
    return MemoryCache(cfg.cache.max_memory_mb * 1000, cfg.cache.ttl_seconds)
