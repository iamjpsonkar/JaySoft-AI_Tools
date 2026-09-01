"""Tests for jsat.tools.query. CI-safe: stdlib sqlite3 only, no AI provider needed."""
from __future__ import annotations

import pytest

from jsat._graph.sqlite import SQLiteGraph
from jsat._models import GraphConfig, JSATConfig
from jsat.tools.query import QueryTool


@pytest.fixture
def graph(tmp_path):
    cfg = GraphConfig(path=str(tmp_path / "g.db"))
    g = SQLiteGraph(cfg)

    # Service A entities
    g.add_node("ep::a1", "Endpoint", {"method": "GET", "route": "/a/one", "service": "svc-a"})
    g.add_node("tbl::a1", "Table", {"name": "a_orders", "service": "svc-a"})
    g.add_node("fn::a1", "Function", {"name": "a_handler", "file": "a.py", "service": "svc-a"})
    g.add_node("cls::a1", "Class", {"name": "AHandler", "file": "a.py", "service": "svc-a"})

    # Service B entities
    g.add_node("ep::b1", "Endpoint", {"method": "GET", "route": "/b/one", "service": "svc-b"})
    g.add_node("tbl::b1", "Table", {"name": "b_orders", "service": "svc-b"})
    g.add_node("fn::b1", "Function", {"name": "b_handler", "file": "b.py", "service": "svc-b"})
    g.add_node("cls::b1", "Class", {"name": "BHandler", "file": "b.py", "service": "svc-b"})

    g.commit()
    yield g
    g.close()


def _tool(graph):
    return QueryTool(graph=graph, cfg=JSATConfig(), ai=None)


@pytest.mark.ci
def test_service_scope_includes_only_matching_endpoint(graph):
    ctx = _tool(graph)._build_context("question", 8192, "svc-a")
    assert "/a/one" in ctx
    assert "/b/one" not in ctx


@pytest.mark.ci
def test_service_scope_includes_only_matching_table(graph):
    ctx = _tool(graph)._build_context("question", 8192, "svc-a")
    assert "a_orders" in ctx
    assert "b_orders" not in ctx


@pytest.mark.ci
def test_service_scope_includes_only_matching_function(graph):
    ctx = _tool(graph)._build_context("handler", 8192, "svc-a")
    assert "a_handler" in ctx
    assert "b_handler" not in ctx


@pytest.mark.ci
def test_service_scope_includes_only_matching_class(graph):
    ctx = _tool(graph)._build_context("handler", 8192, "svc-a")
    assert "AHandler" in ctx
    assert "BHandler" not in ctx


@pytest.mark.ci
def test_no_service_scope_includes_both(graph):
    ctx = _tool(graph)._build_context("handler", 8192, None)
    assert "/a/one" in ctx and "/b/one" in ctx
    assert "a_orders" in ctx and "b_orders" in ctx
