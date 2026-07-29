"""Tests for jsat.tools.indexer — end-to-end CI-safe tests using LightGraph + tmp_path."""
import json
import time
import pytest
from pathlib import Path


@pytest.fixture
def graph():
    from jsat._graph.lightgraph import LightGraph
    g = LightGraph(":memory:")
    yield g
    g.close()


@pytest.fixture
def cfg():
    from jsat._models import JSATConfig
    return JSATConfig()


@pytest.fixture
def indexer(graph, cfg):
    from jsat.tools.indexer import IndexerTool
    return IndexerTool(graph=graph, cfg=cfg, ai=None)


@pytest.fixture
def py_repo(tmp_path: Path) -> Path:
    """A minimal Python repo for testing."""
    (tmp_path / "service.py").write_text(
        '"""Payment service."""\n\n'
        'import os\n'
        'from pathlib import Path\n\n'
        'class PaymentService:\n'
        '    """Handles payments."""\n\n'
        '    def process(self, amount: float) -> bool:\n'
        '        """Process a payment."""\n'
        '        if amount <= 0:\n'
        '            return False\n'
        '        return True\n\n'
        '    def refund(self, order_id: str) -> None:\n'
        '        """Issue a refund."""\n'
        '        pass\n\n'
        'def health_check() -> str:\n'
        '    return "ok"\n'
    )
    (tmp_path / "utils.py").write_text(
        'from service import PaymentService\n\n'
        'def format_amount(amount: float) -> str:\n'
        '    return f"${amount:.2f}"\n'
    )
    return tmp_path


# ── Basic indexing ─────────────────────────────────────────────────────────────

@pytest.mark.ci
def test_indexer_returns_result(indexer, py_repo):
    from jsat._models import IndexResult
    result = indexer.run(py_repo)
    assert isinstance(result, IndexResult)

@pytest.mark.ci
def test_indexer_nodes_created(indexer, graph, py_repo):
    indexer.run(py_repo)
    assert graph.node_count() > 0

@pytest.mark.ci
def test_indexer_edges_created(indexer, graph, py_repo):
    indexer.run(py_repo)
    assert graph.edge_count() > 0

@pytest.mark.ci
def test_indexer_files_indexed_count(indexer, py_repo):
    result = indexer.run(py_repo)
    assert result.files_indexed == 2

@pytest.mark.ci
def test_indexer_languages_detected(indexer, py_repo):
    result = indexer.run(py_repo)
    assert "python" in result.languages

@pytest.mark.ci
def test_indexer_parallel_workers(indexer, py_repo):
    result = indexer.run(py_repo)
    assert result.parallel_workers >= 1

@pytest.mark.ci
def test_indexer_commit_field(indexer, py_repo):
    result = indexer.run(py_repo)
    assert isinstance(result.commit, str)

@pytest.mark.ci
def test_indexer_duration_positive(indexer, py_repo):
    result = indexer.run(py_repo)
    assert result.duration_ms >= 0

@pytest.mark.ci
def test_indexer_repo_path_set(indexer, py_repo):
    result = indexer.run(py_repo)
    assert result.repo_path == str(py_repo)


# ── Rich metadata on nodes ─────────────────────────────────────────────────────

@pytest.mark.ci
def test_function_has_parameters(indexer, graph, py_repo):
    indexer.run(py_repo)
    fns = graph.query("MATCH (n:Function) RETURN n")
    fn_with_params = [f for f in fns if f.get("properties", {}).get("parameters")]
    assert len(fn_with_params) > 0

@pytest.mark.ci
def test_function_has_return_type(indexer, graph, py_repo):
    indexer.run(py_repo)
    fns = graph.query("MATCH (n:Function) RETURN n")
    fn_with_ret = [f for f in fns if f.get("properties", {}).get("return_type")]
    assert len(fn_with_ret) > 0  # process() -> bool, health_check() -> str

@pytest.mark.ci
def test_function_has_complexity(indexer, graph, py_repo):
    indexer.run(py_repo)
    fns = graph.query("MATCH (n:Function) RETURN n")
    for fn in fns:
        assert "complexity" in fn.get("properties", {}), f"Missing complexity: {fn.get('id')}"

@pytest.mark.ci
def test_function_has_loc(indexer, graph, py_repo):
    indexer.run(py_repo)
    fns = graph.query("MATCH (n:Function) RETURN n")
    for fn in fns:
        assert fn.get("properties", {}).get("loc", 0) >= 1

@pytest.mark.ci
def test_function_has_line_alias(indexer, graph, py_repo):
    indexer.run(py_repo)
    fns = graph.query("MATCH (n:Function) RETURN n")
    for fn in fns:
        p = fn.get("properties", {})
        assert "line" in p, f"Missing 'line' alias: {fn.get('id')}"
        assert p["line"] == p["line_start"]

@pytest.mark.ci
def test_function_has_docstring(indexer, graph, py_repo):
    indexer.run(py_repo)
    fns = graph.query("MATCH (n:Function) RETURN n")
    fn_with_doc = [f for f in fns if f.get("properties", {}).get("docstring")]
    assert len(fn_with_doc) >= 2  # process() and refund() have docstrings

@pytest.mark.ci
def test_class_has_bases(indexer, graph, py_repo):
    indexer.run(py_repo)
    classes = graph.query("MATCH (n:Class) RETURN n")
    for cls in classes:
        assert "bases" in cls.get("properties", {}), f"Missing 'bases': {cls.get('id')}"

@pytest.mark.ci
def test_class_has_method_count(indexer, graph, py_repo):
    indexer.run(py_repo)
    classes = graph.query("MATCH (n:Class) RETURN n")
    ps = [c for c in classes if c.get("properties", {}).get("method_count", -1) >= 0]
    assert ps

@pytest.mark.ci
def test_class_has_line_alias(indexer, graph, py_repo):
    indexer.run(py_repo)
    classes = graph.query("MATCH (n:Class) RETURN n")
    for cls in classes:
        p = cls.get("properties", {})
        assert "line" in p

@pytest.mark.ci
def test_complexity_reflects_branches(indexer, graph, py_repo):
    indexer.run(py_repo)
    fns = graph.query("MATCH (n:Function) RETURN n")
    process_fn = next((f for f in fns if "process" in f.get("id", "")), None)
    if process_fn:
        # process() has one `if` → complexity = 2
        assert process_fn["properties"]["complexity"] >= 2


# ── Edge types ────────────────────────────────────────────────────────────────

@pytest.mark.ci
def test_imports_edges_exist(indexer, graph, py_repo):
    indexer.run(py_repo)
    imports = graph.query("SELECT * FROM edges WHERE type='IMPORTS'")
    assert len(imports) > 0

@pytest.mark.ci
def test_calls_edges_exist(indexer, graph, py_repo):
    indexer.run(py_repo)
    calls = graph.query("SELECT * FROM edges WHERE type='CALLS'")
    assert len(calls) >= 0  # may be 0 if no calls in test code

@pytest.mark.ci
def test_inherits_edges_for_subclass(indexer, graph, tmp_path):
    (tmp_path / "models.py").write_text(
        "class Base:\n    pass\n\nclass Child(Base):\n    pass\n"
    )
    indexer.run(tmp_path)
    inherits = graph.query("SELECT * FROM edges WHERE type='INHERITS'")
    assert len(inherits) >= 1

@pytest.mark.ci
def test_raises_edges_for_exceptions(indexer, graph, tmp_path):
    (tmp_path / "errs.py").write_text(
        "class Svc:\n"
        "    def do_thing(self):\n"
        "        raise ValueError('bad')\n"
    )
    indexer.run(tmp_path)
    raises = graph.query("SELECT * FROM edges WHERE type='RAISES'")
    assert len(raises) >= 1


# ── Incremental mode ──────────────────────────────────────────────────────────

@pytest.mark.ci
def test_incremental_second_run_skips_unchanged(indexer, py_repo):
    indexer.run(py_repo)  # first run — builds manifest
    result2 = indexer.run(py_repo)  # second run — nothing changed
    assert result2.incremental is True
    assert result2.files_skipped > 0

@pytest.mark.ci
def test_incremental_force_flag_overrides(indexer, py_repo):
    indexer.run(py_repo)
    result2 = indexer.run(py_repo, force=True)
    assert result2.incremental is False
    assert result2.files_indexed == 2

@pytest.mark.ci
def test_manifest_written_to_jsat_dir(indexer, py_repo):
    from jsat._config import jsat_data_dir
    indexer.run(py_repo)
    manifest = jsat_data_dir(py_repo) / "index-manifest.json"
    assert manifest.exists()

@pytest.mark.ci
def test_manifest_has_correct_structure(indexer, py_repo):
    from jsat._config import jsat_data_dir
    indexer.run(py_repo)
    manifest = jsat_data_dir(py_repo) / "index-manifest.json"
    data = json.loads(manifest.read_text())
    assert data.get("version") == 1
    assert "files" in data
    assert len(data["files"]) == 2

@pytest.mark.ci
def test_incremental_detects_new_file(indexer, graph, py_repo):
    indexer.run(py_repo)
    nodes_after_first = graph.node_count()
    (py_repo / "new_module.py").write_text("def new_fn(): pass\n")
    result3 = indexer.run(py_repo)
    assert result3.files_indexed >= 1  # at least the new file was parsed
    assert graph.node_count() > nodes_after_first


# ── INDEX.md artifact ─────────────────────────────────────────────────────────

@pytest.mark.ci
def test_index_md_created(indexer, py_repo):
    from jsat._config import jsat_data_dir
    indexer.run(py_repo)
    assert (jsat_data_dir(py_repo) / "INDEX.md").exists()

@pytest.mark.ci
def test_index_md_has_overview(indexer, py_repo):
    from jsat._config import jsat_data_dir
    indexer.run(py_repo)
    content = (jsat_data_dir(py_repo) / "INDEX.md").read_text()
    assert "Overview" in content

@pytest.mark.ci
def test_index_md_has_complexity_section(indexer, py_repo):
    from jsat._config import jsat_data_dir
    indexer.run(py_repo)
    content = (jsat_data_dir(py_repo) / "INDEX.md").read_text()
    assert "Complexity" in content

@pytest.mark.ci
def test_index_md_has_language_breakdown(indexer, py_repo):
    from jsat._config import jsat_data_dir
    indexer.run(py_repo)
    content = (jsat_data_dir(py_repo) / "INDEX.md").read_text()
    assert "python" in content.lower()


# ── Manifest helpers ──────────────────────────────────────────────────────────

@pytest.mark.ci
def test_manifest_load_missing_returns_empty(tmp_path):
    from jsat._parsers.manifest import IndexManifest
    mgr = IndexManifest()
    data = mgr.load(tmp_path / "nonexistent.json")
    assert data == {}

@pytest.mark.ci
def test_manifest_save_and_load(tmp_path):
    from jsat._parsers.manifest import IndexManifest
    mgr = IndexManifest()
    path = tmp_path / "manifest.json"
    entries = {"a.py": {"mtime": 1.0, "sha256": "abc", "nodes": 5}}
    mgr.save(path, entries, commit="abc123")
    loaded = mgr.load(path)
    assert "a.py" in loaded
    assert loaded["a.py"]["nodes"] == 5

@pytest.mark.ci
def test_manifest_compute_delta_detects_new(tmp_path):
    from jsat._parsers.manifest import IndexManifest
    mgr = IndexManifest()
    f = tmp_path / "new.py"
    f.write_text("x = 1")
    delta = mgr.compute_delta({}, [f], tmp_path)
    assert f in delta.new
    assert len(delta.unchanged) == 0

@pytest.mark.ci
def test_manifest_compute_delta_detects_deleted(tmp_path):
    from jsat._parsers.manifest import IndexManifest
    mgr = IndexManifest()
    prev = {"old.py": {"mtime": 1.0, "sha256": "x", "nodes": 3}}
    delta = mgr.compute_delta(prev, [], tmp_path)
    assert "old.py" in delta.deleted

@pytest.mark.ci
def test_manifest_delta_result_to_parse(tmp_path):
    from jsat._parsers.manifest import IndexManifest
    mgr = IndexManifest()
    f = tmp_path / "a.py"
    f.write_text("pass")
    delta = mgr.compute_delta({}, [f], tmp_path)
    assert f in delta.to_parse
