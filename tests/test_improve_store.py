"""Tests for jsat._improve._store — clustering, atomicity, and the write guard."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from jsat._improve import _store


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    monkeypatch.setenv("JSAT_IMPROVE_DIR", str(tmp_path / "improve"))
    return tmp_path / "improve"


def _record(fp="abc123", version="0.4.7", source="cli"):
    return {
        "fingerprint": fp, "kind": "crash", "exc_type": "IndexNotFound",
        "message_class": "No JSAT index found for", "op": "query",
        "frames": ["jsat/tools/query.py:run"], "ts": "2026-08-15T09:00:00Z",
        "jsat_version": version, "source": source, "detail": {},
    }


@pytest.mark.ci
def test_improve_dir_honours_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("JSAT_IMPROVE_DIR", str(tmp_path / "custom"))
    assert _store.improve_dir() == (tmp_path / "custom").resolve()


@pytest.mark.ci
def test_improve_dir_defaults_under_home(monkeypatch):
    monkeypatch.delenv("JSAT_IMPROVE_DIR", raising=False)
    assert _store.improve_dir() == Path.home() / ".jsat" / "improve"


# ── the write guard: the structural anti-self-patch guarantee ─────────────────

@pytest.mark.ci
def test_safe_write_refuses_targets_outside_the_store(tmp_path):
    import jsat
    outside = Path(jsat.__file__).resolve().parent / "_evil.py"
    with pytest.raises(ValueError, match="refusing to write"):
        _store._safe_write(outside, "malicious")
    assert not outside.exists()


@pytest.mark.ci
def test_safe_write_allows_explicit_temp_root(tmp_path):
    target = tmp_path / "sandbox" / "f.txt"
    _store._safe_write(target, "ok", extra_root=tmp_path)
    assert target.read_text() == "ok"


@pytest.mark.ci
def test_safe_write_is_atomic_and_leaves_no_tmp(_isolated_store):
    path = _store.improve_dir() / "x.json"
    _store._safe_write(path, '{"a": 1}')
    assert json.loads(path.read_text()) == {"a": 1}
    assert list(_store.improve_dir().glob("*.tmp")) == []


# ── clustering ────────────────────────────────────────────────────────────────

@pytest.mark.ci
def test_merge_cluster_creates_then_increments():
    clusters = _store.merge_cluster({}, _record())
    assert clusters["abc123"]["count"] == 1

    clusters = _store.merge_cluster(clusters, _record())
    assert clusters["abc123"]["count"] == 2
    assert clusters["abc123"]["versions"]["0.4.7"] == 2


@pytest.mark.ci
def test_merge_cluster_tracks_versions_separately():
    """One bug spanning two releases stays ONE cluster with a version breakdown."""
    clusters = _store.merge_cluster({}, _record(version="0.4.6"))
    clusters = _store.merge_cluster(clusters, _record(version="0.4.7"))
    assert len(clusters) == 1
    assert clusters["abc123"]["count"] == 2
    assert clusters["abc123"]["versions"] == {"0.4.6": 1, "0.4.7": 1}


@pytest.mark.ci
def test_merge_cluster_accepts_batched_counts():
    clusters = _store.merge_cluster({}, _record(), count=5)
    assert clusters["abc123"]["count"] == 5


@pytest.mark.ci
def test_write_clusters_evicts_over_cap():
    clusters = {}
    for i in range(10):
        clusters = _store.merge_cluster(clusters, _record(fp=f"fp{i:03d}"), count=i)
    _store.write_clusters(clusters, max_clusters=3)

    kept = _store.read_clusters()
    assert len(kept) == 3
    assert set(kept) == {"fp009", "fp008", "fp007"}  # highest counts survive


# ── signals JSONL ─────────────────────────────────────────────────────────────

@pytest.mark.ci
def test_append_signals_writes_jsonl(_isolated_store):
    _store.append_signals([_record(), _record(fp="def456")])
    lines = (_store.improve_dir() / "signals.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["fingerprint"] == "abc123"


@pytest.mark.ci
def test_append_signals_noop_on_empty():
    _store.append_signals([])
    assert not (_store.improve_dir() / "signals.jsonl").exists()


@pytest.mark.ci
def test_state_roundtrip_has_defaults():
    state = _store.read_state()
    assert state["last_nudge_ts"] == 0.0
    assert state["dropped_count"] == 0

    state["dropped_count"] = 4
    _store.write_state(state)
    assert _store.read_state()["dropped_count"] == 4


@pytest.mark.ci
def test_read_helpers_tolerate_corrupt_files(_isolated_store):
    _store.improve_dir().mkdir(parents=True, exist_ok=True)
    (_store.improve_dir() / "clusters.json").write_text("{not json")
    assert _store.read_clusters() == {}
