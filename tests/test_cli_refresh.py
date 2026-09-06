"""Tests for `jsat refresh`: version check + skill re-sync across connected AIs.

Everything here is offline-safe: the PyPI lookups are stubbed, HOME/XDG are
redirected into a tmp dir so no real tool config is touched, and the skill
writers are exercised against throwaway source copies so the installed package
is never modified. Mirrors `tests/test_codex_connect.py` style.
"""
from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from jsat.cli import app

runner = CliRunner()


def _fake_home(monkeypatch, tmp_path, *, xdg=None):
    """Point Path.home() at a throwaway dir (same trick as the codex tests)."""
    import jsat._cli_refresh as mod

    home = tmp_path / "home"
    mod.Path.home = classmethod(lambda cls: home)
    if xdg:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    return home


def _stub_pypi(monkeypatch):
    """Make _pypi_version return a fixed (installed, latest) pair offline."""
    import jsat._cli_refresh as mod

    def fake_pypi():
        return "0.4.20", "0.4.21", ""
    monkeypatch.setattr(mod, "_pypi_version", fake_pypi)


def _wire_claude(monkeypatch, repo, home, *, scope="project"):
    """Create a fake Claude Code config that `refresh` will see as connected."""
    base = home / ".claude" if scope == "global" else repo / ".claude"
    cfg_path = base / "settings.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps({"mcpServers": {"jsat": {"command": "jsat"}}}), encoding="utf-8")


@pytest.mark.ci
def test_refresh_check_only_detects_drift_without_writing(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    home = _fake_home(monkeypatch, tmp_path)
    _stub_pypi(monkeypatch)
    _wire_claude(monkeypatch, repo, home, scope="project")

    commands_dir = repo / ".claude" / "commands"
    commands_dir.mkdir(parents=True)
    (commands_dir / "jsat.md").write_text("stale dispatcher", encoding="utf-8")

    result = runner.invoke(app, ["refresh", "--check-only", "--ai", "claude", "--repo", str(repo)])

    assert result.exit_code == 0
    assert "would re-sync" in result.output
    # Check-only must NOT touch the installed dispatcher or write anything new.
    assert (commands_dir / "jsat.md").read_text(encoding="utf-8") == "stale dispatcher"


@pytest.mark.ci
def test_refresh_syncs_drifting_skill(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    home = _fake_home(monkeypatch, tmp_path)
    _stub_pypi(monkeypatch)
    _wire_claude(monkeypatch, repo, home, scope="project")

    commands_dir = repo / ".claude" / "commands"
    commands_dir.mkdir(parents=True)
    (commands_dir / "jsat.md").write_text("stale dispatcher", encoding="utf-8")

    result = runner.invoke(app, ["refresh", "--ai", "claude", "--repo", str(repo)])

    assert result.exit_code == 0
    assert "re-synced" in result.output
    assert "stale dispatcher" not in (commands_dir / "jsat.md").read_text(encoding="utf-8")

    # Second run must now report up to date (idempotent).
    again = runner.invoke(app, ["refresh", "--check-only", "--ai", "claude", "--repo", str(repo)])
    assert "up to date" in again.output


@pytest.mark.ci
def test_refresh_skips_unconnected_peers(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _fake_home(monkeypatch, tmp_path)
    _stub_pypi(monkeypatch)

    result = runner.invoke(app, ["refresh", "--ai", "codex", "--repo", str(repo)])

    assert result.exit_code == 0
    assert "not connected" in result.output


@pytest.mark.ci
def test_refresh_rejects_unknown_ai(monkeypatch, tmp_path):
    _fake_home(monkeypatch, tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    result = runner.invoke(app, ["refresh", "--ai", "not-a-tool", "--repo", str(repo)])
    assert result.exit_code == 2


@pytest.mark.ci
def test_refresh_no_skills_skips_sync(monkeypatch, tmp_path):
    _fake_home(monkeypatch, tmp_path)
    _stub_pypi(monkeypatch)
    repo = tmp_path / "repo"
    repo.mkdir()
    result = runner.invoke(app, ["refresh", "--no-skills", "--repo", str(repo)])
    assert result.exit_code == 0
    assert "Version:" in result.output
    assert "Skills:" not in result.output


@pytest.mark.ci
def test_refresh_version_offline_still_syncs(monkeypatch, tmp_path):
    """PyPI down must not crash or block the skill sync."""
    import jsat._cli_refresh as mod
    monkeypatch.setattr(mod, "_pypi_version", lambda: ("0.4.20", None, "offline"))

    repo = tmp_path / "repo"
    repo.mkdir()
    home = _fake_home(monkeypatch, tmp_path)
    _wire_claude(monkeypatch, repo, home, scope="project")
    result = runner.invoke(app, ["refresh", "--ai", "claude", "--repo", str(repo)])
    assert result.exit_code == 0
    assert "offline" in result.output
    assert "Skills:" in result.output