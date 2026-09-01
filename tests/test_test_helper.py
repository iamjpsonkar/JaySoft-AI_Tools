"""Tests for jsat.tools.test_helper. CI-safe: stdlib sqlite3 only.

Regression coverage for a bug found during a whole-project audit: passing a
FILE path (not a directory) to TestHelperTool.run() silently produced a
self-contradictory "0.0% coverage, 0 untested functions" result, because
Path.rglob() on a file (rather than a directory) yields nothing with no
error — confirmed live via jsat__get_test_gaps(path="jsat/mcp/server.py").
"""
from __future__ import annotations

import pytest

from jsat._graph.sqlite import SQLiteGraph
from jsat._models import GraphConfig, JSATConfig
from jsat.tools.test_helper import TestHelperTool


@pytest.fixture
def graph(tmp_path):
    cfg = GraphConfig(path=str(tmp_path / "g.db"))
    g = SQLiteGraph(cfg)
    g.commit()
    yield g
    g.close()


def _tool(graph):
    return TestHelperTool(graph=graph, cfg=JSATConfig())


@pytest.mark.ci
def test_single_file_with_no_matching_test_is_reported_untested(graph, tmp_path):
    src = tmp_path / "widget.py"
    src.write_text("def widget():\n    return 1\n")

    report = _tool(graph).run(path=src)

    assert report.untested_functions == [str(src)]
    assert report.coverage_pct == 0.0


@pytest.mark.ci
def test_single_file_with_matching_test_is_not_untested(graph, tmp_path):
    src = tmp_path / "widget.py"
    src.write_text("def widget():\n    return 1\n")
    (tmp_path / "test_widget.py").write_text("def test_widget():\n    pass\n")

    report = _tool(graph).run(path=src)

    assert report.untested_functions == []
    assert report.coverage_pct == 100.0


@pytest.mark.ci
def test_single_file_that_is_itself_a_test_file_has_nothing_to_check(graph, tmp_path):
    test_src = tmp_path / "test_widget.py"
    test_src.write_text("def test_widget():\n    pass\n")

    report = _tool(graph).run(path=test_src)

    # A test file has no coverage question to ask about itself — must not be
    # reported as "untested" (and must not silently claim 0.0% either, since
    # that would be the same self-contradictory shape as the original bug).
    assert report.untested_functions == []
