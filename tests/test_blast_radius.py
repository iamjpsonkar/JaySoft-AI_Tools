"""Tests for jsat.tools.blast_radius. CI-safe: stdlib sqlite3 only."""
import pytest

from jsat._graph.sqlite import SQLiteGraph
from jsat._models import GraphConfig, JSATConfig
from jsat.tools.blast_radius import SEVERITY_ORDER, BlastRadiusTool, _classify


@pytest.fixture
def graph(tmp_path):
    cfg = GraphConfig(path=str(tmp_path / "g.db"))
    g = SQLiteGraph(cfg)
    g.add_node("fn::a",   "Function", {"name": "a", "file": "x.py"})
    g.add_node("fn::b",   "Function", {"name": "b", "file": "x.py"})
    g.add_node("fn::c",   "Function", {"name": "c", "file": "x.py"})
    g.add_node("file::x", "File",     {"name": "x", "path": "x.py"})
    g.add_edge("fn::a", "fn::b",   "CALLS")
    g.add_edge("fn::b", "fn::c",   "CALLS")
    g.add_edge("fn::a", "file::x", "IMPORTS")
    g.commit()
    yield g
    g.close()


def _tool(graph):
    return BlastRadiusTool(graph=graph, cfg=JSATConfig(), ai=None)


@pytest.mark.ci
def test_classify_calls_is_breaking():    assert _classify("CALLS") == "breaking"
@pytest.mark.ci
def test_classify_reads_from_breaking():  assert _classify("READS_FROM") == "breaking"
@pytest.mark.ci
def test_classify_implements_degraded():  assert _classify("IMPLEMENTS") == "degraded"
@pytest.mark.ci
def test_classify_depends_on_warning():   assert _classify("DEPENDS_ON") == "warning"
@pytest.mark.ci
def test_classify_imports_warning():      assert _classify("IMPORTS") == "warning"
@pytest.mark.ci
def test_classify_unknown_safe():         assert _classify("UNKNOWN") == "safe"

@pytest.mark.ci
def test_single_hop(graph):
    ids = [i.node_id for i in _tool(graph).run("fn::a", max_depth=1).impacts]
    assert "fn::b" in ids

@pytest.mark.ci
def test_two_hops(graph):
    ids = [i.node_id for i in _tool(graph).run("fn::a", max_depth=2).impacts]
    assert "fn::b" in ids and "fn::c" in ids

@pytest.mark.ci
def test_depth_limit(graph):
    ids = [i.node_id for i in _tool(graph).run("fn::a", max_depth=1).impacts]
    assert "fn::c" not in ids

@pytest.mark.ci
def test_unknown_target_no_crash(graph):
    r = _tool(graph).run("no_such_node", max_depth=3)
    assert len(r.impacts) == 0

@pytest.mark.ci
def test_summary_has_four_keys(graph):
    s = _tool(graph).run("fn::a", max_depth=5).summary
    assert set(s.keys()) == {"breaking", "degraded", "warning", "safe"}

@pytest.mark.ci
def test_summary_totals_match_impacts(graph):
    r = _tool(graph).run("fn::a", max_depth=5)
    assert sum(r.summary.values()) == len(r.impacts)

@pytest.mark.ci
def test_mermaid_diagram(graph):
    assert _tool(graph).run("fn::a", max_depth=2).mermaid_diagram.startswith("graph LR")

@pytest.mark.ci
def test_target_in_report(graph):
    assert _tool(graph).run("fn::a", max_depth=1).target == "fn::a"

@pytest.mark.ci
def test_duration_non_negative(graph):
    assert _tool(graph).run("fn::a", max_depth=1).duration_ms >= 0

@pytest.mark.ci
def test_imports_edge_is_warning(graph):
    impacts = [i for i in _tool(graph).run("fn::a", max_depth=1).impacts if i.node_id == "file::x"]
    assert impacts and impacts[0].severity == "warning"

@pytest.mark.ci
def test_impacts_sorted_by_severity(graph):
    impacts = _tool(graph).run("fn::a", max_depth=5).impacts
    order = [SEVERITY_ORDER.get(i.severity, 99) for i in impacts]
    assert order == sorted(order)

# "no start nodes found" warning must actually be reachable — _resolve_target
# must not fabricate a fake start node out of an unresolved target string.
@pytest.mark.ci
def test_resolve_target_returns_empty_for_unknown_target(graph):
    assert _tool(graph)._resolve_target("totally-unknown-thing") == []

@pytest.mark.ci
def test_unknown_target_triggers_no_start_nodes_warning(graph):
    import jsat._call_context as call_context

    call_context._call_ctx.events = []
    try:
        result = _tool(graph).run("totally-unknown-thing", max_depth=3)
        events = list(call_context._call_ctx.events)
    finally:
        # Remove the attribute entirely rather than setting it to None: this
        # thread-local is shared process-wide (the main pytest thread runs
        # every test in this session), and leaving `.events = None` behind
        # previously broke unrelated tests elsewhere (e.g.
        # test_mcp_server.py's hard-timeout tests, whose
        # `getattr(_call_ctx, "events", [])[-5:]` call is only safe when the
        # attribute is either absent or a real list, never None).
        del call_context._call_ctx.events

    assert result.impacts == []
    assert any("no start nodes" in e.lower() for e in events)
