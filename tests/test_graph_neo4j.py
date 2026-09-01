"""Tests for jsat._graph.neo4j — SQL-vs-Cypher guard on Neo4jGraph.query().

Regression coverage for the bug where Neo4jGraph.query() forwarded raw SQLite
SQL (as produced by every jsat/tools/* call site) straight to session.run(),
either crashing with an opaque Cypher parse error or letting callers swallow it
into a silent, wrong empty result. These tests exercise only the SQL-detection
guard, not real Neo4j connectivity — the `neo4j` driver package is not required.
"""
import pytest

from jsat._exceptions import GraphQueryError
from jsat._graph.neo4j import Neo4jGraph, _looks_like_sql


@pytest.mark.ci
@pytest.mark.parametrize(
    "query",
    [
        "SELECT id, label FROM nodes WHERE label=?",
        "select id from nodes",
        "  SELECT * FROM edges",
        "MATCH (n) WHERE json_extract(n.properties, '$.name') = 'x' RETURN n",
    ],
)
def test_looks_like_sql_detects_sqlite_queries(query):
    assert _looks_like_sql(query) is True


@pytest.mark.ci
@pytest.mark.parametrize(
    "query",
    [
        "MATCH (n:Function {id: $id}) RETURN n",
        "MERGE (a)-[r:CALLS]->(b)",
        "RETURN count(*) AS c",
    ],
)
def test_looks_like_sql_allows_cypher(query):
    assert _looks_like_sql(query) is False


@pytest.mark.ci
def test_neo4j_graph_query_raises_typed_error_for_sql():
    """Neo4jGraph.query() must fail loud and clear on SQL input, not crash raw
    or silently return an empty/wrong result.

    Bypasses __init__ (which requires a live Neo4j connection) since the SQL
    guard in query() must trigger before any driver session is touched.
    """
    graph = object.__new__(Neo4jGraph)
    with pytest.raises(GraphQueryError) as exc_info:
        graph.query("SELECT id, label FROM nodes WHERE label=?", ["Function"])
    assert "SQL query" in str(exc_info.value)
    assert exc_info.value.query == "SELECT id, label FROM nodes WHERE label=?"
