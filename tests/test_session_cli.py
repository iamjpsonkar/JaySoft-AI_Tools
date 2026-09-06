"""Tests for `jsat session save` / `jsat session continue` — capturing working
context from anywhere into the same resumable session format the skills use."""
from __future__ import annotations

import pytest
from typer.testing import CliRunner

from jsat import _sessions
from jsat.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("JSAT_SESSIONS_DIR", str(tmp_path / "sessions"))
    yield


def _latest() -> _sessions.Session | None:
    return _sessions.latest()


# ── save ──────────────────────────────────────────────────────────────────────

@pytest.mark.ci
def test_save_writes_a_resumable_session():
    r = runner.invoke(app, [
        "session", "save", "harden the login flow",
        "--step", "audit token handling",
        "--finding", "tokens are 60s TTL",
    ])
    assert r.exit_code == 0, r.output

    sessions = _sessions.list_sessions()
    assert len(sessions) == 1
    s = sessions[0]
    assert s.skill == "session"
    assert s.task == "harden the login flow"
    assert s.status == "in_progress"
    assert [st.name for st in s.steps] == ["audit token handling"]
    assert s.next_step is not None and s.next_step.name == "audit token handling"
    assert any("tokens are 60s TTL" in f for f in s.findings)


@pytest.mark.ci
def test_save_without_steps_gets_one_default_step():
    r = runner.invoke(app, ["session", "save", "just a thought"])
    assert r.exit_code == 0, r.output
    s = _latest()
    assert s is not None and len(s.steps) == 1
    assert s.next_step is not None


@pytest.mark.ci
def test_save_multiple_steps_keeps_their_order():
    r = runner.invoke(app, [
        "session", "save", "ship the retry",
        "--step", "alpha", "--step", "beta", "--step", "gamma",
    ])
    assert r.exit_code == 0, r.output
    steps = [st.name for st in _latest().steps]
    assert steps == ["alpha", "beta", "gamma"]


@pytest.mark.ci
def test_save_rejects_invalid_status():
    r = runner.invoke(app, ["session", "save", "task", "--status", "banana"])
    assert r.exit_code != 0
    assert _sessions.list_sessions() == []


@pytest.mark.ci
def test_save_rejects_blank_task():
    r = runner.invoke(app, ["session", "save", "   "])
    assert r.exit_code != 0
    assert _sessions.list_sessions() == []


@pytest.mark.ci
def test_save_records_repo_context(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = runner.invoke(app, ["session", "save", "context capture", "--step", "x"])
    assert r.exit_code == 0, r.output
    assert any("**context:** repo=" in f for f in _latest().findings)


@pytest.mark.ci
def test_save_no_context_skips_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = runner.invoke(app, ["session", "save", "no ctx", "--no-context",
                            "--step", "x"])
    assert r.exit_code == 0, r.output
    assert not any("**context:**" in f for f in _latest().findings)


@pytest.mark.ci
def test_save_honours_skill_grouping():
    runner.invoke(app, ["session", "save", "a deploy thing", "--skill", "deploy"])
    s = _latest()
    assert s.skill == "deploy"
    assert s.path.name.startswith("deploy-")


# ── continue ──────────────────────────────────────────────────────────────────

@pytest.mark.ci
def test_continue_no_arg_resumes_newest_in_progress():
    runner.invoke(app, ["session", "save", "first thing",
                        "--step", "alpha", "--step", "beta"])
    r = runner.invoke(app, ["session", "continue"])
    assert r.exit_code == 0, r.output
    assert "Next step: alpha" in r.output


@pytest.mark.ci
def test_continue_by_fragment_resolves_the_named_session():
    runner.invoke(app, ["session", "save", "named work", "--step", "alpha"])
    s = _latest()
    r = runner.invoke(app, ["session", "continue", s.path.stem])
    assert r.exit_code == 0, r.output
    assert "Next step: alpha" in r.output


@pytest.mark.ci
def test_continue_reports_when_nothing_left():
    runner.invoke(app, ["session", "save", "finish me", "--step", "done"])
    s = _latest()
    s.complete_step("done")
    r = runner.invoke(app, ["session", "continue"])
    assert r.exit_code == 0, r.output
    assert "Nothing left to do" in r.output