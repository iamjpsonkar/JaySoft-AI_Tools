"""Tests for jsat.tools.incident. CI-safe: scores methods directly (no git)."""
from __future__ import annotations
import math
from datetime import datetime, timezone, timedelta
from typing import Any, Iterator
import pytest
from jsat._models import JSATConfig
from jsat.tools.incident import IncidentTool

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
def tool(): return IncidentTool(graph=NoOpGraph(), cfg=JSATConfig(), ai=None)

def _commit(summary, hours_ago, files=None):
    authored = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return {"hash": "a"*40, "summary": summary, "author": "dev",
            "timestamp": authored.isoformat(), "files": files or [],
            "authored_datetime": authored}

@pytest.mark.ci
def test_recent_scores_higher(tool):
    assert tool._score(_commit("fix", 1.0), "error") > tool._score(_commit("fix", 48.0), "error")

@pytest.mark.ci
def test_pattern_match_raises_score(tool):
    matching  = _commit("payment timeout regression", 10.0)
    unrelated = _commit("update README docs", 10.0)
    assert tool._score(matching, "timeout in payment") > tool._score(unrelated, "timeout in payment")

@pytest.mark.ci
def test_score_in_unit_interval(tool):
    for h in [0.1, 1, 12, 72, 240]:
        s = tool._score(_commit("x", h), "error")
        assert 0.0 <= s <= 1.0

@pytest.mark.ci
def test_more_files_higher_score(tool):
    few  = _commit("p", 2.0, files=["a.py"])
    many = _commit("p", 2.0, files=[f"f{i}.py" for i in range(30)])
    assert tool._score(many, "error") > tool._score(few, "error")

@pytest.mark.ci
def test_recency_decay_monotone(tool):
    lam = IncidentTool.LAMBDA
    s = [math.exp(-lam * h) for h in [1, 6, 24, 72]]
    assert s == sorted(s, reverse=True)

@pytest.mark.ci
def test_parse_hours_h(tool): assert tool._parse_hours("72h") == 72.0
@pytest.mark.ci
def test_parse_hours_d(tool): assert tool._parse_hours("3d") == 72.0
@pytest.mark.ci
def test_parse_hours_whitespace(tool): assert tool._parse_hours("  24h  ") == 24.0
@pytest.mark.ci
def test_parse_hours_default(tool): assert tool._parse_hours("week") == 72.0

@pytest.mark.ci
def test_evidence_has_hash(tool):
    c = _commit("broke payment", 3.0)
    assert c["hash"][:8] in " ".join(tool._evidence(c, "payment failure"))

@pytest.mark.ci
def test_mitigations_non_empty_with_hypothesis(tool):
    from jsat._models import Hypothesis
    h = Hypothesis(score=0.9, commit_hash="a"*40, commit_summary="broke it", evidence=[])
    assert len(tool._mitigations([h])) >= 1

@pytest.mark.ci
def test_mitigations_non_empty_empty_list(tool):
    assert len(tool._mitigations([])) >= 1

@pytest.mark.ci
def test_incident_report_model():
    from jsat._models import IncidentReport
    r = IncidentReport(description="err", hypotheses=[], mitigation_steps=["check infra"], duration_ms=0)
    assert r.hypotheses == [] and len(r.mitigation_steps) >= 1
