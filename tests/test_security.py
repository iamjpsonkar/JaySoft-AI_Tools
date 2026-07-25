"""Tests for jsat.tools.security. CI-safe: no Semgrep binary needed."""
from __future__ import annotations
import math
from pathlib import Path
from typing import Any, Iterator
import pytest
from jsat._models import JSATConfig
from jsat.tools.security import SecurityTool, _entropy

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
def tool(): return SecurityTool(graph=NoOpGraph(), cfg=JSATConfig(), ai=None)

# Entropy
@pytest.mark.ci
def test_entropy_low_for_plain_word(tool):
    assert _entropy("password") < 4.0

@pytest.mark.ci
def test_entropy_high_for_random_string(tool):
    assert _entropy("aB3dEfGhIjKlMnOpQrStUvWxYz012345") > 4.0

@pytest.mark.ci
def test_entropy_empty_string(tool):
    assert _entropy("") == 0.0

@pytest.mark.ci
def test_entropy_single_char(tool):
    assert _entropy("aaaa") == 0.0

# Secret detection
@pytest.mark.ci
def test_no_secrets_in_clean_file(tool, tmp_path):
    f = tmp_path / "clean.py"
    f.write_text("def add(a, b):\n    return a + b\nGREETING = 'hello'\n")
    import structlog
    log = structlog.get_logger("test")
    assert tool._detect_secrets(tmp_path, log) == 0

@pytest.mark.ci
def test_finds_high_entropy_token(tool, tmp_path):
    # Use a realistic high-entropy string (mixed chars, not all the same)
    # Shannon entropy must be > 4.5 (the default threshold)
    # "sk-" + diverse alphanumeric chars gives entropy ~5.5
    token = "sk-aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789ab"
    f = tmp_path / "secret.py"
    f.write_text(f'API_KEY = "{token}"\n')
    import structlog
    log = structlog.get_logger("test")
    assert tool._detect_secrets(tmp_path, log) >= 1

# Severity filtering
@pytest.mark.ci
def test_severity_passes_critical_beats_medium(tool):
    from jsat.tools.security import _SEVERITY_ORDER
    assert _SEVERITY_ORDER.get("critical", 0) >= _SEVERITY_ORDER.get("medium", 0)

@pytest.mark.ci
def test_severity_info_below_high(tool):
    from jsat.tools.security import _SEVERITY_ORDER
    assert _SEVERITY_ORDER.get("info", 0) < _SEVERITY_ORDER.get("high", 0)

# Run() — graceful when no Semgrep
@pytest.mark.ci
def test_run_no_semgrep_no_crash(tool, tmp_path):
    report = tool.run(path=tmp_path, severity_threshold="medium")
    assert isinstance(report.findings, list)
    assert isinstance(report.cves, list)
    assert isinstance(report.secrets_found, int) and report.secrets_found >= 0
    assert isinstance(report.duration_ms, int) and report.duration_ms >= 0

@pytest.mark.ci
def test_run_returns_security_report_type(tool, tmp_path):
    from jsat._models import SecurityReport
    assert isinstance(tool.run(path=tmp_path), SecurityReport)
