"""Tests for jsat.tools.contract. CI-safe: exercises `_classify` on crafted diff text
directly — no real git repo or network calls needed."""
from __future__ import annotations

import pytest

from jsat._models import JSATConfig
from jsat.tools.contract import ContractTool


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
def tool():
    return ContractTool(graph=NoOpGraph(), cfg=JSATConfig(), ai=None)


@pytest.mark.ci
def test_newly_required_true_marker_is_breaking(tool):
    diff = (
        "--- a/spec.yaml\n"
        "+++ b/spec.yaml\n"
        "@@ -1,3 +1,4 @@\n"
        " properties:\n"
        "   email:\n"
        "     type: string\n"
        "+    required: true\n"
    )
    changes = tool._classify(diff)
    added = [c for c in changes if c["change_type"] != "removed"]
    breaking = [c for c in added if c["is_breaking"]]
    assert len(breaking) == 1
    assert "required: true" in breaking[0]["content"]
    assert breaking[0]["change_type"] == "field_added_required"


@pytest.mark.ci
def test_newly_required_list_item_is_breaking(tool):
    diff = (
        "--- a/spec.yaml\n"
        "+++ b/spec.yaml\n"
        "@@ -1,4 +1,5 @@\n"
        " required:\n"
        "   - name\n"
        "+  - email\n"
        " properties:\n"
    )
    changes = tool._classify(diff)
    breaking = [c for c in changes if c["is_breaking"]]
    assert len(breaking) == 1
    assert breaking[0]["content"] == "- email"
    assert breaking[0]["change_type"] == "field_added_required"


@pytest.mark.ci
def test_newly_optional_field_is_not_breaking(tool):
    diff = (
        "--- a/spec.yaml\n"
        "+++ b/spec.yaml\n"
        "@@ -1,2 +1,3 @@\n"
        " properties:\n"
        "+  nickname:\n"
        "+    type: string\n"
    )
    changes = tool._classify(diff)
    assert all(not c["is_breaking"] for c in changes if c["change_type"] != "removed")


@pytest.mark.ci
def test_removed_endpoint_still_breaking(tool):
    diff = (
        "--- a/spec.yaml\n"
        "+++ b/spec.yaml\n"
        "@@ -1,2 +1,1 @@\n"
        "-/legacy/endpoint:\n"
        "-  get:\n"
    )
    changes = tool._classify(diff)
    assert any(c["is_breaking"] and c["change_type"] == "endpoint_removed" for c in changes)
