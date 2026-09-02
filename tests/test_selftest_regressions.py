"""
Regressions for the defects the no-mocking self-test surfaced at 0.4.17.

Each test names the failure mode it locks down, because several of these bugs
were invisible in the worst possible way: the tool returned a confident empty
answer rather than an error. CI-safe — no network, no external services.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from jsat._exceptions import GraphCapacityError
from jsat._graph.lightgraph import LightGraph
from jsat._graph.sqlite import SQLiteGraph
from jsat._models import GraphConfig, IndexerConfig

pytestmark = pytest.mark.ci


# ── graph.edges(): two MCP tools called a method that did not exist ──────────

@pytest.fixture(params=[SQLiteGraph, LightGraph])
def graph(request, tmp_path):
    cfg = GraphConfig(path=str(tmp_path / "graph" / "graph.db"))
    Path(cfg.path).parent.mkdir(parents=True, exist_ok=True)
    g = request.param(cfg)
    yield g
    g.close()


def test_edges_returns_every_edge(graph):
    """get_data_flow and get_consumers both call graph.edges()."""
    graph.add_node("a", "Function", {"name": "a"})
    graph.add_node("b", "Function", {"name": "b"})
    graph.add_edge("a", "b", "CALLS", {})
    graph.add_edge("a", "b", "READS_FROM", {})
    edges = graph.edges()
    assert len(edges) == 2
    assert {e["type"] for e in edges} == {"CALLS", "READS_FROM"}
    assert all({"source", "target", "type", "properties"} <= set(e) for e in edges)


def test_edges_filters_by_type(graph):
    graph.add_node("a", "Function", {})
    graph.add_node("b", "Function", {})
    graph.add_edge("a", "b", "CALLS", {})
    graph.add_edge("a", "b", "WRITES_TO", {})
    assert [e["type"] for e in graph.edges(edge_types=["WRITES_TO"])] == ["WRITES_TO"]
    assert graph.edges(edge_types=["CONSUMES"]) == []


def test_edges_honours_limit(graph):
    graph.add_node("a", "Function", {})
    for i in range(5):
        graph.add_node(f"t{i}", "Function", {})
        graph.add_edge("a", f"t{i}", "CALLS", {})
    assert len(graph.edges(limit=2)) == 2


def test_graph_client_declares_edges():
    """It must be part of the contract, not a backend-specific extra."""
    from jsat._graph import GraphClient
    assert hasattr(GraphClient, "edges")


# ── capacity caps were configurable but never enforced ──────────────────────

def test_bulk_insert_beyond_max_nodes_raises(tmp_path):
    cfg = GraphConfig(path=str(tmp_path / "g.db"), max_nodes=5, max_edges=100)
    g = SQLiteGraph(cfg)
    try:
        g.bulk_add_nodes([{"id": f"n{i}", "label": "File", "properties": {}}
                          for i in range(3)])
        assert g.node_count() == 3
        with pytest.raises(GraphCapacityError) as exc:
            g.bulk_add_nodes([{"id": f"m{i}", "label": "File", "properties": {}}
                              for i in range(10)])
        assert exc.value.max_nodes == 5
    finally:
        g.close()


def test_bulk_insert_beyond_max_edges_raises(tmp_path):
    cfg = GraphConfig(path=str(tmp_path / "g.db"), max_nodes=1000, max_edges=2)
    g = SQLiteGraph(cfg)
    try:
        with pytest.raises(GraphCapacityError):
            g.bulk_add_edges([{"source": "a", "target": f"b{i}", "type": "CALLS",
                               "properties": {}} for i in range(5)])
    finally:
        g.close()


def test_default_caps_do_not_block_ordinary_use(tmp_path):
    cfg = GraphConfig(path=str(tmp_path / "g.db"))
    g = SQLiteGraph(cfg)
    try:
        g.bulk_add_nodes([{"id": f"n{i}", "label": "File", "properties": {}}
                          for i in range(500)])
        assert g.node_count() == 500
    finally:
        g.close()


# ── every parser's language must be indexed by default ──────────────────────

def test_default_languages_cover_every_parser():
    """TypeScript is documented as core support, and Java/Ruby/Rust ship with
    jsat[standard]; a narrower default silently skipped those files."""
    from jsat._parsers import detect_language
    defaults = set(IndexerConfig().languages)
    for suffix in (".py", ".js", ".ts", ".go", ".java", ".rb", ".rs"):
        lang = detect_language(Path(f"x{suffix}"))
        assert lang is not None, suffix
        assert lang in defaults, f"{suffix} ({lang}) is not indexed by default"


# ── a single-file security scan silently scanned nothing ────────────────────

def test_secret_scan_of_a_single_file_finds_the_secret(tmp_path):
    """Path.rglob on a FILE yields nothing, so security_scan_file used to
    report a clean bill of health for any file at all."""
    from jsat._models import JSATConfig
    from jsat.tools.security import SecurityTool

    target = tmp_path / "config.py"
    fake_key = "AKIA" + "EXAMPLE" + "0NOTREAL" + "9"
    target.write_text(f'AWS_ACCESS_KEY_ID = "{fake_key}"\n')

    tool = SecurityTool(graph=None, cfg=JSATConfig())
    report = tool.run(path=target, severity_threshold="low", include_deps=False)
    assert report.secrets_found >= 1
    assert any(fake_key not in str(f) for f in report.findings)  # value not echoed


def test_directory_security_scan_still_works(tmp_path):
    from jsat._models import JSATConfig
    from jsat.tools.security import SecurityTool

    (tmp_path / "config.py").write_text(
        'AWS_ACCESS_KEY_ID = "' + "AKIA" + "EXAMPLE" + "0NOTREAL" + '9"\n')
    tool = SecurityTool(graph=None, cfg=JSATConfig())
    report = tool.run(path=tmp_path, severity_threshold="low", include_deps=False)
    assert report.secrets_found >= 1


# ── import replaced the db under a live connection ──────────────────────────

def test_import_archive_reopens_the_graph(tmp_path, monkeypatch):
    """restore() replaces the database file; without re-creating the client
    the caller reads the empty database it had just opened (or a closed one)."""
    from jsat._core import JSAT

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("def add(a, b):\n    return a + b\n")
    monkeypatch.setenv("JSAT_DATA_DIR", str(tmp_path / "data-a"))
    monkeypatch.setenv("JSAT_IMPROVE_DIR", str(tmp_path / "improve"))
    monkeypatch.setenv("JSAT_SESSIONS_DIR", str(tmp_path / "sessions"))

    js = JSAT(repo=str(repo))
    js.index(force=True)
    before = js.index_status["nodes"]
    assert before > 0
    archive = tmp_path / "out.jsat.zip"
    js.export(output=archive)

    monkeypatch.setenv("JSAT_DATA_DIR", str(tmp_path / "data-b"))
    js2 = JSAT(repo=str(repo))
    js2._get_graph()               # open it first — this is what broke
    js2.import_archive(archive)
    assert js2.index_status["nodes"] == before


def test_reload_graph_drops_the_cached_client(tmp_path, monkeypatch):
    from jsat._core import JSAT
    monkeypatch.setenv("JSAT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("JSAT_IMPROVE_DIR", str(tmp_path / "improve"))
    repo = tmp_path / "repo"
    repo.mkdir()
    js = JSAT(repo=str(repo))
    first = js._get_graph()
    js.reload_graph()
    assert js._graph is None
    assert js._get_graph() is not first


# ── the skill registry duplicated the command files and drifted ─────────────

def test_jsat_skills_is_derived_from_the_shipped_command_files():
    from jsat._cli_skills_data import _JSAT_SKILLS
    commands_dir = Path(__file__).resolve().parent.parent / "jsat" / "commands"
    expected = {p.stem for p in commands_dir.glob("jsat-*.md")} - {"jsat-help"}
    assert set(_JSAT_SKILLS) == expected


def test_every_skill_has_a_description_and_a_body():
    from jsat._cli_skills_data import _JSAT_SKILLS
    assert _JSAT_SKILLS, "registry is empty"
    for name, (description, instruction) in _JSAT_SKILLS.items():
        assert description.strip(), f"{name} has no description"
        assert instruction.strip(), f"{name} has no instruction body"
        assert not description.startswith("---"), f"{name} kept its frontmatter"


# ── slash commands must only name tools that exist ──────────────────────────

def test_slash_commands_reference_only_registered_tools():
    import re
    from unittest.mock import MagicMock

    from jsat.mcp.server import MCPServer

    real = set(MCPServer(MagicMock())._registry)
    commands_dir = Path(__file__).resolve().parent.parent / "jsat" / "commands"
    negation = re.compile(
        r"(there is no|does not exist|is not an? (?:mcp )?tool|not a tool|"
        r"no such tool|do not (?:literally )?call)", re.I)
    bogus: dict[str, str] = {}
    for path in sorted(commands_dir.glob("*.md")):
        text = path.read_text()
        for m in re.finditer(r"jsat__([a-z_][a-z0-9_]*)", text):
            if negation.search(text[max(0, m.start() - 160):m.end() + 160]):
                continue
            if m.group(1) not in real:
                bogus[m.group(1)] = path.name
    assert not bogus, f"slash commands name nonexistent tools: {bogus}"


# ── every registered tool must be reachable by a named role ─────────────────

def test_every_tool_is_reachable_by_a_named_role():
    from unittest.mock import MagicMock

    from jsat.mcp.server import _ROLE_PERMISSIONS, MCPServer

    real = set(MCPServer(MagicMock())._registry)
    granted: set[str] = set()
    for role, tools in _ROLE_PERMISSIONS.items():
        if role != "admin":
            granted |= set(tools)
    # import_index replaces the whole graph, so it is admin-only by design.
    assert real - granted == {"import_index"}


# ── the CI template must only call commands that exist ──────────────────────

def test_ci_setup_template_only_calls_real_commands(tmp_path):
    import re

    from typer.testing import CliRunner

    from jsat._cli_common import app

    runner = CliRunner()
    result = runner.invoke(app, ["ci-setup"], env={"HOME": str(tmp_path)})
    generated = list(tmp_path.rglob("*.yml")) + list(Path.cwd().glob(".github/workflows/jsat.yml"))
    text = "\n".join(p.read_text() for p in generated if p.exists()) or result.output
    if not text.strip():
        pytest.skip("ci-setup produced no inspectable workflow here")
    called = set(re.findall(r"jsat\s+([a-z][a-z0-9-]*)", text))
    help_out = runner.invoke(app, ["--help"]).output
    for name in called:
        assert name in help_out, f"generated CI calls `jsat {name}`, which does not exist"


# ── the CVE tool reported "not implemented" for a working capability ────────

def test_dependency_cve_tool_is_not_a_stub(tmp_path):
    """It used to return {"status": "not_implemented"} while the same osv.dev
    lookup was already shipping and working inside security_review."""
    from jsat._models import JSATConfig
    from jsat.mcp.server import _get_dependency_cves_impl

    class FakeJSAT:
        _repo = tmp_path
        _cfg = JSATConfig()

        def _get_graph(self):
            return None

    # No requirements file: the honest answer is an empty result set, not a
    # "planned for a future version" notice.
    out = _get_dependency_cves_impl(FakeJSAT(), str(tmp_path), 7.0)
    assert out.get("status") != "not_implemented"
    assert "cves" in out
    assert out["cvss_min"] == 7.0
    assert out["count"] == 0


# ── MCP file arguments resolve against the repo, not the server's cwd ───────

def test_repo_path_resolves_relative_against_the_repo(tmp_path):
    from jsat.mcp.server import _repo_path

    class FakeJSAT:
        _repo = tmp_path

    resolved = _repo_path(FakeJSAT(), "svc/config.py")
    assert Path(resolved).is_absolute()
    assert resolved == str((tmp_path / "svc" / "config.py").resolve())


def test_repo_path_leaves_absolute_paths_alone(tmp_path):
    from jsat.mcp.server import _repo_path

    class FakeJSAT:
        _repo = tmp_path

    absolute = "/etc/hosts"
    assert _repo_path(FakeJSAT(), absolute) == absolute


def test_repo_path_defaults_to_the_repo_root(tmp_path):
    from jsat.mcp.server import _repo_path

    class FakeJSAT:
        _repo = tmp_path

    assert _repo_path(FakeJSAT(), None) == str(tmp_path.resolve())


# ── skill clusters must name real commands ─────────────────────────────────

def test_skill_clusters_reference_real_commands():
    from jsat.skills.clusters import BUILT_IN_CLUSTERS

    commands_dir = Path(__file__).resolve().parent.parent / "jsat" / "commands"
    known = {p.stem.removeprefix("jsat-") for p in commands_dir.glob("jsat-*.md")}
    dangling = {c: [s for s in skills if s not in known]
                for c, skills in BUILT_IN_CLUSTERS.items()}
    dangling = {c: m for c, m in dangling.items() if m}
    assert not dangling, f"clusters name nonexistent commands: {dangling}"


# ── the dead second tool catalogue is gone ─────────────────────────────────

def test_dead_mcp_tools_module_is_gone():
    with pytest.raises(ImportError):
        import jsat.mcp.tools  # noqa: F401


# ── export copied the db file while the data was still in the WAL ──────────

def test_export_after_index_in_the_same_process_is_not_empty(tmp_path, monkeypatch):
    """The archive was a valid, readable, EMPTY database while its manifest
    reported the true node count — a backup that silently held nothing."""
    from jsat._core import JSAT

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text(
        "def add(a, b):\n    return a + b\n\n"
        "class Greeter:\n    def greet(self):\n        return add(1, 2)\n")
    monkeypatch.setenv("JSAT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("JSAT_IMPROVE_DIR", str(tmp_path / "improve"))
    monkeypatch.setenv("JSAT_SESSIONS_DIR", str(tmp_path / "sessions"))

    js = JSAT(repo=str(repo))
    js.index(force=True)
    expected = js.index_status["nodes"]
    assert expected > 0

    archive = tmp_path / "out.jsat.zip"
    js.export(output=archive)

    import sqlite3
    with zipfile.ZipFile(archive) as z:
        assert "graph/graph.db" in z.namelist()
        extracted = tmp_path / "extracted.db"
        extracted.write_bytes(z.read("graph/graph.db"))
        manifest = json.loads(z.read("manifest.json"))

    conn = sqlite3.connect(str(extracted))
    try:
        in_archive = next(conn.execute("SELECT count(*) FROM nodes"))[0]
    finally:
        conn.close()
    assert in_archive == expected, (
        f"archive holds {in_archive} nodes but the graph had {expected} "
        f"(manifest claims {manifest.get('nodes')})")
    assert manifest["nodes"] == expected


def test_graph_checkpoint_moves_wal_into_the_main_file(tmp_path):
    from jsat._models import GraphConfig

    cfg = GraphConfig(path=str(tmp_path / "g.db"))
    g = SQLiteGraph(cfg)
    try:
        g.bulk_add_nodes([{"id": f"n{i}", "label": "File", "properties": {}}
                          for i in range(50)])
        g.checkpoint()
        import sqlite3
        conn = sqlite3.connect(str(tmp_path / "g.db"))
        try:
            assert next(conn.execute("SELECT count(*) FROM nodes"))[0] == 50
        finally:
            conn.close()
    finally:
        g.close()


def test_graph_client_declares_checkpoint():
    from jsat._graph import GraphClient
    assert hasattr(GraphClient, "checkpoint")


# ── profile presets overrode explicitly configured values ──────────────────

def _all_services_up():
    from jsat._models import SystemProfile
    return SystemProfile(
        ram_gb=32, cpu_arch="x86_64", gpu="none", is_ci=False,
        ollama_up=True, neo4j_up=True, qdrant_up=True, redis_up=True,
        detected_profile="team",
    )


def test_explicit_graph_backend_survives_the_team_preset():
    """With a Neo4j container running for some unrelated project, the `team`
    preset overrode an explicit `graph.backend: sqlite` and indexing failed
    outright trying to reach Bolt."""
    from jsat._config import auto_configure
    from jsat._models import GraphConfig, JSATConfig

    cfg = JSATConfig()
    cfg.graph = GraphConfig(backend="sqlite")
    out = auto_configure(cfg, _all_services_up())
    assert out.graph.backend == "sqlite"


def test_explicit_cache_and_embeddings_survive_the_team_preset():
    from jsat._config import auto_configure
    from jsat._models import CacheConfig, EmbeddingsConfig, JSATConfig

    cfg = JSATConfig()
    cfg.cache = CacheConfig(backend="memory")
    cfg.embeddings = EmbeddingsConfig(provider="none")
    out = auto_configure(cfg, _all_services_up())
    assert out.cache.backend == "memory"
    assert out.embeddings.provider == "none"


def test_preset_still_applies_when_nothing_is_explicit():
    """The fix must not turn auto-configuration off."""
    from jsat._config import auto_configure
    from jsat._models import JSATConfig

    out = auto_configure(JSATConfig(), _all_services_up())
    assert out.graph.backend == "neo4j"
    assert out.cache.backend == "redis"


def test_explicit_ai_provider_still_survives():
    """The original special case this generalises must keep working."""
    from jsat._config import auto_configure
    from jsat._models import AIConfig, JSATConfig

    cfg = JSATConfig()
    cfg.ai = AIConfig(provider="codex_cli")
    out = auto_configure(cfg, _all_services_up())
    assert out.ai.provider == "codex_cli"


# ── selecting the redis cache without a URI crashed ────────────────────────

def test_redis_cache_backend_without_a_uri_does_not_crash():
    """`redis_uri` defaults to None, so `cache.backend: redis` died on
    `None.startswith` deep inside the client."""
    from jsat._cache import _DEFAULT_REDIS_URI, get_cache
    from jsat._models import CacheConfig, JSATConfig

    cfg = JSATConfig()
    cfg.cache = CacheConfig(backend="redis")
    assert cfg.cache.redis_uri is None
    # Either a RedisCache pointed at the documented default, or a clean
    # fallback — never an AttributeError.
    try:
        cache = get_cache(cfg)
    except Exception as e:
        assert not isinstance(e, AttributeError), f"crashed on a None URI: {e}"
        return
    assert cache is not None
    assert _DEFAULT_REDIS_URI == "redis://localhost:6379"
