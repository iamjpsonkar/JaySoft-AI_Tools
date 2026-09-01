"""Tests for jsat.tools.security. CI-safe: no Semgrep binary needed."""
from __future__ import annotations

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
    count, _ = tool._detect_secrets(tmp_path, log)
    assert count == 0

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
    count, _ = tool._detect_secrets(tmp_path, log)
    assert count >= 1

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

# severity_threshold must filter secrets and CVEs uniformly, not just Semgrep findings.
@pytest.mark.ci
def test_severity_threshold_filters_secret_findings(tool, tmp_path, monkeypatch):
    from jsat._models import SecurityFinding

    mixed = [
        SecurityFinding(file="a.py", line=1, category="secret_detection",
                        severity="low", title="low secret", description="d"),
        SecurityFinding(file="b.py", line=2, category="secret_detection",
                        severity="critical", title="critical secret", description="d"),
    ]
    monkeypatch.setattr(tool, "_run_semgrep", lambda *a, **kw: [])
    monkeypatch.setattr(tool, "_detect_secrets", lambda *a, **kw: (len(mixed), mixed))
    monkeypatch.setattr(tool, "_check_cves", lambda *a, **kw: [])

    report = tool.run(path=tmp_path, severity_threshold="critical", include_deps=False)

    assert report.secrets_found == 1
    assert all(f.severity == "critical" for f in report.findings)

@pytest.mark.ci
def test_severity_threshold_filters_cve_findings(tool, tmp_path, monkeypatch):
    from jsat._models import CVEFinding

    mixed_cves = [
        CVEFinding(package="pkg-a", version="1.0", cve_id="CVE-1", cvss=3.0,
                   severity="low"),
        CVEFinding(package="pkg-b", version="2.0", cve_id="CVE-2", cvss=9.5,
                   severity="critical"),
    ]
    monkeypatch.setattr(tool, "_run_semgrep", lambda *a, **kw: [])
    monkeypatch.setattr(tool, "_detect_secrets", lambda *a, **kw: (0, []))
    monkeypatch.setattr(tool, "_check_cves", lambda *a, **kw: mixed_cves)

    report = tool.run(path=tmp_path, severity_threshold="critical", include_deps=True)

    assert len(report.cves) == 1
    assert report.cves[0].cve_id == "CVE-2"

@pytest.mark.ci
def test_severity_threshold_medium_keeps_everything_at_or_above(tool, tmp_path, monkeypatch):
    from jsat._models import CVEFinding, SecurityFinding

    secrets = [
        SecurityFinding(file="a.py", line=1, category="secret_detection",
                        severity="low", title="x", description="d"),
        SecurityFinding(file="a.py", line=2, category="secret_detection",
                        severity="high", title="y", description="d"),
    ]
    cves = [
        CVEFinding(package="p", version="1", cve_id="CVE-3", cvss=8.0, severity="high"),
    ]
    monkeypatch.setattr(tool, "_run_semgrep", lambda *a, **kw: [])
    monkeypatch.setattr(tool, "_detect_secrets", lambda *a, **kw: (len(secrets), secrets))
    monkeypatch.setattr(tool, "_check_cves", lambda *a, **kw: cves)

    report = tool.run(path=tmp_path, severity_threshold="medium", include_deps=True)

    assert report.secrets_found == 1  # only "high" passes "medium" threshold
    assert len(report.cves) == 1


# Entropy fallback must not false-positive on regex-pattern-literal source or
# ordinary long identifiers — confirmed live on this repo's own jsat/_secrets.py
# and jsat/_config.py before this fix (whitespace-split tokens included
# surrounding punctuation, inflating entropy on non-secret text).
@pytest.mark.ci
def test_entropy_fallback_ignores_regex_pattern_literal(tool, tmp_path):
    f = tmp_path / "patterns.py"
    f.write_text(
        "_P = (re.compile(r'\\\\bgh[ps]_[A-Za-z0-9]{36}\\\\b'), \"critical\")\n"
    )
    import structlog
    log = structlog.get_logger("test")
    count, findings = tool._detect_secrets(tmp_path, log)
    entropy_findings = [x for x in findings if x.rule_id == "jsat.secret.high_entropy"]
    assert entropy_findings == []


@pytest.mark.ci
def test_entropy_fallback_ignores_long_identifier(tool, tmp_path):
    f = tmp_path / "config.py"
    f.write_text("detected_profile_from_system_environment_probe = detected\n")
    import structlog
    log = structlog.get_logger("test")
    count, findings = tool._detect_secrets(tmp_path, log)
    entropy_findings = [x for x in findings if x.rule_id == "jsat.secret.high_entropy"]
    assert entropy_findings == []


@pytest.mark.ci
def test_entropy_fallback_ignores_sequential_charset_literal(tool, tmp_path):
    f = tmp_path / "sanitize.py"
    f.write_text('_SAFE_STR_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789_")\n')
    import structlog
    log = structlog.get_logger("test")
    count, findings = tool._detect_secrets(tmp_path, log)
    entropy_findings = [x for x in findings if x.rule_id == "jsat.secret.high_entropy"]
    assert entropy_findings == []


@pytest.mark.ci
def test_sequential_charset_literal_helper():
    from jsat.tools.security import _is_sequential_charset_literal

    assert _is_sequential_charset_literal("abcdefghijklmnopqrstuvwxyz0123456789_")
    assert _is_sequential_charset_literal("0123456789")
    assert not _is_sequential_charset_literal("aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789ab")


@pytest.mark.ci
def test_entropy_fallback_still_catches_real_looking_secret_in_punctuated_line(tool, tmp_path):
    # A real secret embedded in a quoted assignment (punctuation around it)
    # must still be caught — the fix narrows the *charset*, not the ability
    # to find a token inside a normal line of code.
    token = "aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789ab"
    f = tmp_path / "leak.py"
    f.write_text(f'SOME_TOKEN = "{token}"  # oops\n')
    import structlog
    log = structlog.get_logger("test")
    count, findings = tool._detect_secrets(tmp_path, log)
    entropy_findings = [x for x in findings if x.rule_id == "jsat.secret.high_entropy"]
    assert len(entropy_findings) >= 1
