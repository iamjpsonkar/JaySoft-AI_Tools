"""Tests for jsat.tools.knowledge. CI-safe: stdlib sqlite3 only, no AI provider.

Regression coverage for a bug found during a whole-project audit: repeated
ingestion of the same living doc (CLAUDE.md, an ADR, a runbook) accumulated
a brand-new, content-addressed entry per edit forever, since entry_id is a
hash of (category, text) and nothing ever superseded the prior version.
"""
from __future__ import annotations

import pytest

from jsat._graph.sqlite import SQLiteGraph
from jsat._models import GraphConfig, JSATConfig
from jsat.tools.knowledge import KnowledgeTool


@pytest.fixture
def graph(tmp_path):
    cfg = GraphConfig(path=str(tmp_path / "g.db"))
    g = SQLiteGraph(cfg)
    yield g
    g.close()


def _tool(graph):
    return KnowledgeTool(graph=graph, cfg=JSATConfig(), ai=None)


@pytest.mark.ci
def test_add_stores_source_path(graph):
    tool = _tool(graph)
    tool.add("some durable fact worth remembering here", source_path="docs/adr-1.md")
    entries = tool.list_entries()
    assert len(entries) == 1
    assert entries[0]["source_path"] == "docs/adr-1.md"
    assert entries[0]["stale"] is False


@pytest.mark.ci
def test_reingesting_a_changed_file_supersedes_the_old_entry(graph, tmp_path):
    tool = _tool(graph)
    doc = tmp_path / "adr.md"

    doc.write_text("# ADR 1\n\nWe decided to use SQLite for the default backend.\n")
    tool.ingest_file(doc)

    doc.write_text("# ADR 1\n\nWe decided to use SQLite, then switched to Postgres.\n")
    tool.ingest_file(doc)

    entries = tool.list_entries()
    stale = [e for e in entries if e["stale"]]
    live = [e for e in entries if not e["stale"]]

    # The first ingestion's entry must be superseded (stale), not left to
    # accumulate forever alongside the new one.
    assert len(stale) >= 1
    assert any("Postgres" in e["text"] for e in live)
    assert not any("Postgres" in e["text"] for e in stale)


@pytest.mark.ci
def test_reingesting_an_unchanged_file_does_not_duplicate_live_entries(graph, tmp_path):
    tool = _tool(graph)
    doc = tmp_path / "adr.md"
    doc.write_text("# ADR 1\n\nWe decided to use SQLite for the default backend.\n")

    tool.ingest_file(doc)
    tool.ingest_file(doc)  # same content, re-ingested

    live = [e for e in tool.list_entries() if not e["stale"]]
    # Same (category, text) hashes to the same entry_id both times — an
    # unchanged re-ingest must not leave two live copies of the same fact.
    assert len(live) == 1
