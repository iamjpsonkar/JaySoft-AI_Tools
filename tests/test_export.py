"""Tests for jsat.tools.export. CI-safe: builds crafted zips in tmp_path only."""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from jsat._exceptions import ImportCorrupted
from jsat._models import JSATConfig
from jsat.tools.export import ExportTool


class NoOpGraph:
    def node_count(self): return 0
    def edge_count(self): return 0
    def bfs(self, *a, **kw): return iter([])
    def query(self, *a, **kw): return []
    def get_node(self, *a): return None
    def outgoing_edges(self, *a): return []
    def add_node(self, *a, **kw): pass
    def add_edge(self, *a, **kw): pass
    def close(self): pass


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Isolated JSAT data dir. `restore` anchors artifacts here (via
    jsat_data_dir), not to `./.jsat` relative to the process cwd — the old
    behaviour scattered them wherever the caller happened to be, which for an
    MCP server is the editor's working directory."""
    d = tmp_path / "jsat-data"
    monkeypatch.setenv("JSAT_DATA_DIR", str(d))
    return d


@pytest.fixture
def tool(data_dir):
    return ExportTool(graph=NoOpGraph(), cfg=JSATConfig(), ai=None)


def _make_archive(path: Path, manifest: dict, artifact_entries: dict[str, bytes]) -> Path:
    """Build a .jsat.zip with a manifest + arbitrary (possibly malicious) artifact entries."""
    import json

    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        for name, data in artifact_entries.items():
            zf.writestr(name, data)
    return path


@pytest.mark.ci
def test_zip_slip_relative_traversal_rejected(tool, tmp_path, data_dir,
                                              monkeypatch):
    """A crafted entry using ../../ must not write outside the data dir."""
    monkeypatch.chdir(tmp_path)
    from jsat import __version__ as JSAT_VERSION

    archive = _make_archive(
        tmp_path / "evil.jsat.zip",
        {"jsat_version": JSAT_VERSION, "nodes": 0, "edges": 0},
        {"artifacts/../../../tmp/pwned.txt": b"pwned"},
    )

    with pytest.raises(ImportCorrupted):
        tool.restore(archive)

    # Nothing must have escaped the tmp_path sandbox.
    assert not (tmp_path.parent.parent / "tmp" / "pwned.txt").exists()
    escaped = [p for p in Path("/tmp").glob("pwned.txt")]
    assert not escaped


@pytest.mark.ci
def test_zip_slip_absolute_path_rejected(tool, tmp_path, data_dir,
                                        monkeypatch):
    """A crafted entry using an absolute path must not write outside the data dir."""
    monkeypatch.chdir(tmp_path)
    from jsat import __version__ as JSAT_VERSION

    target = tmp_path / "outside_absolute_pwned.txt"
    archive = _make_archive(
        tmp_path / "evil_abs.jsat.zip",
        {"jsat_version": JSAT_VERSION, "nodes": 0, "edges": 0},
        {f"artifacts/{target}": b"pwned"},
    )

    with pytest.raises(ImportCorrupted):
        tool.restore(archive)

    assert not target.exists()


@pytest.mark.ci
def test_legitimate_artifact_still_restored(tool, tmp_path, data_dir,
                                           monkeypatch):
    """A well-formed archive with a normal artifacts/ entry must still restore
    correctly — into the resolved data dir."""
    monkeypatch.chdir(tmp_path)
    from jsat import __version__ as JSAT_VERSION

    archive = _make_archive(
        tmp_path / "good.jsat.zip",
        {"jsat_version": JSAT_VERSION, "nodes": 1, "edges": 1},
        {"artifacts/INDEX.md": b"# hello"},
    )

    tool.restore(archive)

    restored = data_dir / "INDEX.md"
    assert restored.exists(), (
        f"artifact not restored to the data dir; "
        f"data_dir contains {list(data_dir.rglob('*')) if data_dir.exists() else 'nothing'}")
    assert restored.read_bytes() == b"# hello"
    # And nothing landed in a cwd-relative .jsat/.
    assert not (tmp_path / ".jsat" / "INDEX.md").exists()
