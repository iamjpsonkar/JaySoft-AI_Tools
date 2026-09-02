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
        except Exception as e:
            # Deliberately broad. RedisCache converts a missing `redis`
            # package into ProfileError (NOT an ImportError subclass), and a
            # wrong URI or an unreachable server raises something from the
            # client library — an `except ImportError` here caught none of
            # them, so a `team` profile with a Redis detected but jsat[team]
            # absent aborted instead of degrading. The cache is an
            # optimisation; losing it must never stop the tool.
            import structlog
            structlog.get_logger(__name__).warning(
                "cache_redis_unavailable",
                error=str(e),
                message="cache.backend=redis is not usable; falling back to "
                        "the in-memory cache. For a shared cache install "
                        "'jsat[team]' and check cache.redis_uri.",
            )
    if backend == "disk":
        from jsat._cache.disk import DiskCache
        return DiskCache(cfg.cache.disk_path, cfg.cache.ttl_seconds)
    from jsat._cache.memory import MemoryCache
    return MemoryCache(cfg.cache.max_memory_mb * 1000, cfg.cache.ttl_seconds)
