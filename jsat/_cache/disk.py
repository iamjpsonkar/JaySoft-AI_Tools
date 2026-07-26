"""jsat._cache.disk — Disk-based JSON semantic cache. Zero external deps."""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path


class DiskCache:
    """Atomic disk cache. Each entry is a .json file. Writes are tmp→rename."""

    def __init__(self, cache_dir: str | Path, ttl_seconds: int = 3600) -> None:
        import structlog
        self._log = structlog.get_logger(__name__).bind(backend="DiskCache")
        self._dir = Path(cache_dir)
        self._ttl = ttl_seconds
        self._dir.mkdir(parents=True, exist_ok=True)
        self._log.info("cache_init", cache_dir=str(self._dir), ttl_seconds=ttl_seconds)

    def _path(self, query: str, context_hash: str) -> Path:
        digest = hashlib.sha256(f"{query}::{context_hash}".encode()).hexdigest()[:16]
        return self._dir / f"{digest}.json"

    def _read(self, path: Path) -> dict | None:
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None

    def get(self, query: str, context_hash: str) -> str | None:
        path = self._path(query, context_hash)
        entry = self._read(path)
        if entry is None:
            return None
        if time.monotonic() > entry.get("expires_at", 0.0):
            path.unlink(missing_ok=True)
            self._log.debug("cache_miss_expired", path=path.name)
            return None
        self._log.debug("cache_hit", path=path.name)
        return entry.get("result")

    def set(self, query: str, context_hash: str, result: str,
            affected_files: list[str] = None) -> None:
        if affected_files is None:
            affected_files = []
        path = self._path(query, context_hash)
        tmp = path.with_suffix(".json.tmp")
        payload = {
            "result": result,
            "expires_at": time.monotonic() + self._ttl,
            "affected_files": list(affected_files),
            "query": query,
            "context_hash": context_hash,
        }
        try:
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
            self._log.debug("cache_set", path=path.name)
        except OSError as e:
            self._log.error("cache_write_failed", path=str(path), error=str(e))
            tmp.unlink(missing_ok=True)
            raise

    def invalidate_for_files(self, changed_files: list[str]) -> int:
        if not changed_files:
            return 0
        changed = set(changed_files)
        removed = 0
        for p in self._dir.glob("*.json"):
            entry = self._read(p)
            if entry and changed.intersection(entry.get("affected_files", [])):
                p.unlink(missing_ok=True)
                removed += 1
        self._log.info("cache_invalidated", removed=removed)
        return removed

    def clear(self) -> None:
        removed = 0
        for p in self._dir.glob("*.json*"):
            p.unlink(missing_ok=True)
            removed += 1
        self._log.info("cache_cleared", removed=removed)

    def stats(self) -> dict:
        now = time.monotonic()
        size = sum(
            1 for p in self._dir.glob("*.json")
            if (e := self._read(p)) and now <= e.get("expires_at", 0.0)
        )
        return {"size": size, "cache_dir": str(self._dir.resolve())}
