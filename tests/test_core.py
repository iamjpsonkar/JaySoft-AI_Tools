"""Tests for jsat._core.JSAT — graph backend selection and index freshness.

Regression coverage for two bugs found in a whole-project audit:

1. JSAT._get_graph() only special-cased backend == "neo4j"; setting
   graph.backend to the valid, typed "lightgraph" value silently fell through
   to SQLiteGraph instead of LightGraph.
2. JSAT.index_status hardcoded commit=None and is_fresh=True unconditionally,
   so `jsat doctor` always reported freshness even long after the repo changed
   with no re-index.

These tests construct a bare JSAT instance via __new__ (bypassing __init__,
which does full system detection / AI provider setup) and only set the
attributes the methods under test actually touch (_repo, _cfg, _graph).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from jsat._core import JSAT
from jsat._models import JSATConfig


def _bare_jsat(tmp_path: Path, backend: str = "sqlite") -> JSAT:
    """Build a minimal JSAT instance for unit-testing graph/index-status logic."""
    js = JSAT.__new__(JSAT)
    cfg = JSATConfig()
    cfg = cfg.model_copy(update={
        "graph": cfg.graph.model_copy(update={
            "backend": backend,
            "path": str(tmp_path / "graph.db"),
        })
    })
    js._repo = tmp_path
    js._cfg = cfg
    js._graph = None
    return js


@pytest.fixture(autouse=True)
def isolate_jsat_data(monkeypatch, tmp_path: Path) -> None:
    """Keep every test out of the user's global ~/.jsat directory."""
    monkeypatch.setenv("JSAT_DATA_DIR", str(tmp_path / "jsat-data"))


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """A tiny git repo with one commit, for commit-based freshness checks."""
    git = pytest.importorskip("git")
    repo = git.Repo.init(tmp_path)
    (tmp_path / "a.txt").write_text("hello")
    repo.index.add(["a.txt"])
    author = git.Actor("Test", "test@example.com")
    repo.index.commit("initial commit", author=author, committer=author)
    return tmp_path


@pytest.mark.ci
def test_get_graph_lightgraph_backend_returns_lightgraph(tmp_path):
    from jsat._graph.lightgraph import LightGraph
    js = _bare_jsat(tmp_path, backend="lightgraph")
    graph = js._get_graph()
    try:
        assert isinstance(graph, LightGraph)
        # Cached on second call, not rebuilt.
        assert js._get_graph() is graph
    finally:
        graph.close()


@pytest.mark.ci
def test_get_graph_sqlite_backend_returns_sqlitegraph(tmp_path):
    from jsat._graph.sqlite import SQLiteGraph
    js = _bare_jsat(tmp_path, backend="sqlite")
    graph = js._get_graph()
    try:
        assert isinstance(graph, SQLiteGraph)
    finally:
        graph.close()


@pytest.mark.ci
def test_index_status_not_fresh_when_no_manifest(tmp_path):
    """No index-manifest.json yet (never indexed) => not fresh, commit is None."""
    js = _bare_jsat(tmp_path, backend="lightgraph")
    status = js.index_status
    assert status["commit"] is None
    assert status["is_fresh"] is False
    js._graph.close()


@pytest.mark.ci
def test_index_status_fresh_when_manifest_commit_matches_head(git_repo):
    from jsat._config import jsat_data_dir

    js = _bare_jsat(git_repo, backend="lightgraph")
    current_commit = js._current_git_commit()
    assert current_commit is not None

    manifest_dir = jsat_data_dir(git_repo)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "index-manifest.json").write_text(
        json.dumps({"version": 1, "commit": current_commit, "files": {}})
    )

    status = js.index_status
    assert status["commit"] == current_commit
    assert status["is_fresh"] is True
    js._graph.close()


@pytest.mark.ci
def test_index_status_stale_when_manifest_commit_is_old(git_repo):
    from jsat._config import jsat_data_dir

    js = _bare_jsat(git_repo, backend="lightgraph")

    manifest_dir = jsat_data_dir(git_repo)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "index-manifest.json").write_text(
        json.dumps({"version": 1, "commit": "deadbeef0000", "files": {}})
    )

    status = js.index_status
    assert status["commit"] == "deadbeef0000"
    assert status["is_fresh"] is False
    js._graph.close()
