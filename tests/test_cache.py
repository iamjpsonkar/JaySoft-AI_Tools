"""Tests for jsat._cache.memory and disk. CI-safe — no external deps."""
import time
import pytest
from jsat._cache.memory import MemoryCache
from jsat._cache.disk import DiskCache


@pytest.mark.ci
def test_memory_cache_basic():
    cache = MemoryCache(max_size=10, ttl_seconds=60)
    assert cache.get("q1", "ctx1") is None
    cache.set("q1", "ctx1", "result1")
    assert cache.get("q1", "ctx1") == "result1"


@pytest.mark.ci
def test_memory_cache_miss_different_context():
    cache = MemoryCache(max_size=10, ttl_seconds=60)
    cache.set("q1", "ctx1", "result1")
    assert cache.get("q1", "ctx2") is None


@pytest.mark.ci
def test_memory_cache_lru_eviction():
    cache = MemoryCache(max_size=3, ttl_seconds=60)
    cache.set("q1", "c", "r1")
    cache.set("q2", "c", "r2")
    cache.set("q3", "c", "r3")
    cache.set("q4", "c", "r4")  # evicts q1
    assert cache.get("q1", "c") is None
    assert cache.get("q4", "c") == "r4"


@pytest.mark.ci
def test_memory_cache_ttl_expiry():
    cache = MemoryCache(max_size=10, ttl_seconds=0)  # instant expiry
    cache.set("q1", "c", "result")
    time.sleep(0.01)
    assert cache.get("q1", "c") is None


@pytest.mark.ci
def test_memory_cache_invalidate_for_files():
    cache = MemoryCache(max_size=10, ttl_seconds=60)
    cache.set("q1", "c", "r1", affected_files=["src/pay.py"])
    cache.set("q2", "c", "r2", affected_files=["src/other.py"])
    removed = cache.invalidate_for_files(["src/pay.py"])
    assert removed == 1
    assert cache.get("q1", "c") is None
    assert cache.get("q2", "c") == "r2"


@pytest.mark.ci
def test_memory_cache_stats():
    cache = MemoryCache(max_size=10, ttl_seconds=60)
    cache.set("q", "c", "r")
    cache.get("q", "c")    # hit
    cache.get("q2", "c")   # miss
    s = cache.stats()
    assert s["hits"] == 1
    assert s["misses"] == 1
    assert s["size"] == 1


@pytest.mark.ci
def test_disk_cache_basic(tmp_path):
    cache = DiskCache(cache_dir=tmp_path / "cache", ttl_seconds=60)
    assert cache.get("q1", "ctx") is None
    cache.set("q1", "ctx", "result123")
    assert cache.get("q1", "ctx") == "result123"


@pytest.mark.ci
def test_disk_cache_ttl_expiry(tmp_path):
    cache = DiskCache(cache_dir=tmp_path / "cache", ttl_seconds=0)
    cache.set("q1", "ctx", "result")
    time.sleep(0.01)
    assert cache.get("q1", "ctx") is None


@pytest.mark.ci
def test_disk_cache_invalidate(tmp_path):
    cache = DiskCache(cache_dir=tmp_path / "cache", ttl_seconds=60)
    cache.set("q1", "c", "r1", affected_files=["a.py"])
    cache.set("q2", "c", "r2", affected_files=["b.py"])
    removed = cache.invalidate_for_files(["a.py"])
    assert removed == 1
    assert cache.get("q1", "c") is None
    assert cache.get("q2", "c") == "r2"


@pytest.mark.ci
def test_disk_cache_clear(tmp_path):
    cache = DiskCache(cache_dir=tmp_path / "cache", ttl_seconds=60)
    cache.set("q1", "c", "r1")
    cache.set("q2", "c", "r2")
    cache.clear()
    assert cache.get("q1", "c") is None
    assert cache.stats()["size"] == 0
