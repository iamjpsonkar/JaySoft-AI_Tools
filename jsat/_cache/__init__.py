"""jsat._cache — Cache backend factory."""
from __future__ import annotations

from typing import Any

# Where a Redis lives when the user selected the backend but gave no URI.
# Matching the documented default in docs/configuration.md.
_DEFAULT_REDIS_URI = "redis://localhost:6379"


def get_cache(cfg: Any):
    backend = getattr(cfg.cache, "backend", "memory")
    if backend == "redis":
        try:
            from jsat._cache.redis import RedisCache
            # `redis_uri` defaults to None, so selecting the backend without
            # setting it crashed on `None.startswith` deep inside the client
            # instead of either working or saying what was missing.
            uri = cfg.cache.redis_uri or _DEFAULT_REDIS_URI
            return RedisCache(uri, cfg.cache.ttl_seconds)
        except ImportError:
            import structlog
            structlog.get_logger(__name__).warning(
                "cache_redis_unavailable",
                message="cache.backend=redis needs the redis package; "
                        "falling back to the in-memory cache. "
                        "Install: pip install 'jsat[team]'",
            )
    if backend == "disk":
        from jsat._cache.disk import DiskCache
        return DiskCache(cfg.cache.disk_path, cfg.cache.ttl_seconds)
    from jsat._cache.memory import MemoryCache
    return MemoryCache(cfg.cache.max_memory_mb * 1000, cfg.cache.ttl_seconds)
