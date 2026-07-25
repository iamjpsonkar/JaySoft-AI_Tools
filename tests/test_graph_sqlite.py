"""Tests for jsat._graph.sqlite. CI-safe — only needs sqlite3."""
import pytest
from jsat._graph.sqlite import SQLiteGraph
from jsat._models import GraphConfig


@pytest.fixture
def graph(tmp_path):
    cfg = GraphConfig(path=str(tmp_path / "test.db"))
    g = SQLiteGraph(cfg)
    yield g
    g.close()


@pytest.mark.ci
def test_add_and_get_node(graph):
    graph.add_node("fn::refund", "Function",
                   {"name": "refund", "file": "pay.py", "line_start": 10})
    graph.commit()
    node = graph.get_node("fn::refund")
    assert node is not None
    assert node["label"] == "Function"
    assert node["properties"]["name"] == "refund"


@pytest.mark.ci
def test_get_nonexistent_node(graph):
    assert graph.get_node("does::not::exist") is None


@pytest.mark.ci
def test_add_edge_and_outgoing(graph):
    graph.add_node("fn::a", "Function", {"name": "a"})
    graph.add_node("fn::b", "Function", {"name": "b"})
    graph.add_edge("fn::a", "fn::b", "CALLS")
    graph.commit()
    edges = graph.outgoing_edges("fn::a")
    assert len(edges) == 1
    assert edges[0][0] == "CALLS"
    assert edges[0][1] == "fn::b"


@pytest.mark.ci
def test_node_count(graph):
    assert graph.node_count() == 0
    graph.add_node("n1", "File", {})
    graph.add_node("n2", "File", {})
    graph.commit()
    assert graph.node_count() == 2


@pytest.mark.ci
def test_edge_count(graph):
    graph.add_node("a", "Function", {})
    graph.add_node("b", "Function", {})
    graph.add_edge("a", "b", "CALLS")
    graph.commit()
    assert graph.edge_count() == 1


@pytest.mark.ci
def test_bfs_traversal(graph):
    for nid in ["a", "b", "c", "d"]:
        graph.add_node(nid, "Function", {"name": nid})
    graph.add_edge("a", "b", "CALLS")
    graph.add_edge("b", "c", "CALLS")
    graph.add_edge("c", "d", "CALLS")
    graph.commit()

    visited = list(graph.bfs(["a"], max_depth=3))
    ids = [v[0] for v in visited]
    assert "a" in ids
    assert "b" in ids
    assert "c" in ids
    assert "d" in ids


@pytest.mark.ci
def test_bfs_max_depth(graph):
    for nid in ["a", "b", "c", "d"]:
        graph.add_node(nid, "Function", {"name": nid})
    graph.add_edge("a", "b", "CALLS")
    graph.add_edge("b", "c", "CALLS")
    graph.add_edge("c", "d", "CALLS")
    graph.commit()

    visited = list(graph.bfs(["a"], max_depth=2))
    ids = [v[0] for v in visited]
    assert "d" not in ids  # depth 3, excluded


@pytest.mark.ci
def test_bulk_add_nodes(graph):
    nodes = [{"id": f"n{i}", "label": "File", "properties": {"name": f"f{i}"}}
             for i in range(10)]
    graph.bulk_add_nodes(nodes)
    graph.commit()
    assert graph.node_count() == 10


@pytest.mark.ci
def test_upsert_node(graph):
    graph.add_node("n1", "Function", {"name": "original"})
    graph.commit()
    graph.add_node("n1", "Function", {"name": "updated"})
    graph.commit()
    node = graph.get_node("n1")
    assert node["properties"]["name"] == "updated"
    assert graph.node_count() == 1


@pytest.mark.ci
def test_raw_sql_query(graph):
    graph.add_node("py::main", "Function", {"name": "main", "file": "main.py"})
    graph.commit()
    rows = graph.execute_sql("SELECT id, label FROM nodes WHERE label=?", ["Function"])
    assert len(rows) == 1
    assert rows[0]["id"] == "py::main"
