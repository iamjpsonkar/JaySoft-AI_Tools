"""jsat._cache.redis — Redis semantic cache backend (jsat[team] extra)."""
from __future__ import annotations

import hashlib
import json
import time


class RedisCache:
    """Shared semantic cache backed by Redis. Used in team mode."""

    def __init__(self, redis_uri: str, ttl_seconds: int = 3600) -> None:
        import structlog
        self._log = structlog.get_logger(__name__)

        try:
            import redis as _redis
        except ImportError as e:
            from jsat._exceptions import ProfileError
            raise ProfileError(
                "Redis cache requires the 'team' extra.\nInstall: pip install 'jsat[team]'",
                required_extra="team",
            ) from e

        self._redis = _redis.from_url(redis_uri, decode_responses=True)
        self._ttl = ttl_seconds
        self._prefix = "jsat:cache:"

        # Verify connection
        try:
            self._redis.ping()
            self._log.info("redis_cache_init", uri=self._redact_uri(redis_uri), ttl=ttl_seconds)
        except Exception as e:
            self._log.error("redis_cache_connect_failed", error=str(e))
            raise

    @staticmethod
    def _redact_uri(uri: str) -> str:
        """Remove credentials from URI for safe logging."""
        try:
            from urllib.parse import urlparse, urlunparse
            p = urlparse(uri)
            redacted = p._replace(netloc=f"{p.hostname}:{p.port}" if p.port else p.hostname)
            return urlunparse(redacted)
        except Exception:
            return "[redacted]"

    def _key(self, query: str, context_hash: str) -> str:
        digest = hashlib.sha256(f"{query}\x00{context_hash}".encode()).hexdigest()[:24]
        return f"{self._prefix}{digest}"

    def get(self, query: str, context_hash: str) -> str | None:
        key = self._key(query, context_hash)
        try:
            raw = self._redis.get(key)
            if raw is None:
                self._log.debug("redis_cache_miss", key=key[-12:])
                return None
            entry = json.loads(raw)
            if time.monotonic() > entry.get("expires_at", 0):
                self._redis.delete(key)
                self._log.debug("redis_cache_expired", key=key[-12:])
                return None
            self._log.debug("redis_cache_hit", key=key[-12:])
            return entry["result"]
        except Exception as e:
            self._log.warning("redis_cache_get_error", error=str(e))
            return None

    def set(self, query: str, context_hash: str, result: str,
            affected_files: list[str] = None) -> None:
        if affected_files is None:
            affected_files = []
        key = self._key(query, context_hash)
        payload = json.dumps({
            "result": result,
            "expires_at": time.monotonic() + self._ttl,
            "affected_files": affected_files,
            "query": query[:200],
        })
        try:
            self._redis.setex(key, self._ttl, payload)
            self._log.debug("redis_cache_set", key=key[-12:], result_len=len(result))
        except Exception as e:
            self._log.warning("redis_cache_set_error", error=str(e))

    def invalidate_for_files(self, changed_files: list[str]) -> int:
        if not changed_files:
            return 0
        changed = set(changed_files)
        removed = 0
        try:
            cursor = 0
            while True:
                cursor, keys = self._redis.scan(cursor, match=f"{self._prefix}*", count=100)
                for key in keys:
                    raw = self._redis.get(key)
                    if not raw:
                        continue
                    try:
                        entry = json.loads(raw)
                        if changed.intersection(entry.get("affected_files", [])):
                            self._redis.delete(key)
                            removed += 1
                    except Exception:
                        pass
                if cursor == 0:
                    break
        except Exception as e:
            self._log.warning("redis_cache_invalidate_error", error=str(e))
        self._log.info("redis_cache_invalidated", removed=removed)
        return removed

    def clear(self) -> None:
        try:
            cursor = 0
            removed = 0
            while True:
                cursor, keys = self._redis.scan(cursor, match=f"{self._prefix}*", count=100)
                if keys:
                    self._redis.delete(*keys)
                    removed += len(keys)
                if cursor == 0:
                    break
            self._log.info("redis_cache_cleared", removed=removed)
        except Exception as e:
            self._log.warning("redis_cache_clear_error", error=str(e))

    def stats(self) -> dict:
        try:
            info = self._redis.info("memory")
            count = sum(1 for _ in self._redis.scan_iter(f"{self._prefix}*"))
            return {
                "size": count,
                "redis_used_memory_mb": round(info.get("used_memory", 0) / (1024 * 1024), 1),
                "backend": "redis",
            }
        except Exception as e:
            self._log.warning("redis_cache_stats_error", error=str(e))
            return {"size": 0, "backend": "redis", "error": str(e)}
