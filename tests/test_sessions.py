"""Tests for jsat._sessions — the session format skills use to resume work."""
from __future__ import annotations

import pytest

from jsat import _sessions


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("JSAT_SESSIONS_DIR", str(tmp_path / "sessions"))


@pytest.mark.ci
def test_create_writes_documented_filename_and_format():
    s = _sessions.create("magic", "add retry logic to payments", ["status", "blast-radius"])
    assert s.path.name.startswith("magic-add-retry-logic-to-")
    assert s.path.name.endswith(".md")

    text = s.path.read_text()
    assert text.startswith("---\n")
    assert "skill: magic" in text
    assert "status: in_progress" in text
    assert "## Steps" in text and "## Findings" in text
    assert "- [ ] status" in text


@pytest.mark.ci
def test_roundtrip_preserves_everything():
    s = _sessions.create("crack", "redesign auth", ["architect", "security"])
    s.complete_step("architect", "use JWT with short TTL")

    loaded = _sessions.load(s.path)
    assert loaded is not None
    assert loaded.skill == "crack"
    assert loaded.task == "redesign auth"
    assert loaded.status == "in_progress"
    assert loaded.done_count == 1
    assert loaded.steps[0].done and loaded.steps[0].finding == "use JWT with short TTL"
    assert loaded.next_step is not None and loaded.next_step.name == "security"
    assert loaded.findings == ["**architect:** use JWT with short TTL"]


@pytest.mark.ci
def test_next_step_is_none_when_all_done():
    s = _sessions.create("sprint", "ship it", ["a", "b"])
    s.complete_step("a")
    s.complete_step("b")
    assert _sessions.load(s.path).next_step is None


@pytest.mark.ci
def test_complete_step_is_idempotent_and_reports_unknown():
    s = _sessions.create("magic", "task", ["one"])
    assert s.complete_step("one", "done") is True
    assert s.complete_step("one", "again") is False   # already complete
    assert s.complete_step("nope") is False


@pytest.mark.ci
def test_finish_sets_status():
    s = _sessions.create("magic", "task", ["one"])
    s.finish()
    assert _sessions.load(s.path).status == "completed"


@pytest.mark.ci
def test_finish_rejects_unknown_status():
    s = _sessions.create("magic", "task", [])
    s.finish("banana")
    assert s.status == "completed"


# ── discovery ─────────────────────────────────────────────────────────────────

@pytest.mark.ci
def test_list_and_latest_filter_by_skill_and_status():
    a = _sessions.create("magic", "first task", ["x"])
    b = _sessions.create("crack", "second task", ["y"])
    a.finish()

    assert len(_sessions.list_sessions()) == 2
    assert [s.skill for s in _sessions.list_sessions(skill="crack")] == ["crack"]
    assert [s.status for s in _sessions.list_sessions(status="completed")] == ["completed"]

    latest = _sessions.latest(status="in_progress")
    assert latest is not None and latest.path.name == b.path.name


@pytest.mark.ci
def test_actions_files_are_excluded_from_listings():
    """`<skill>-actions-*.md` is a separate artifact, not a session."""
    _sessions.create("magic", "real task", ["x"])
    (_sessions.sessions_dir() / "magic-actions-real-task-20260815-1000.md").write_text(
        "---\nskill: magic\nstatus: pending\n---\n"
    )
    assert len(_sessions.list_sessions()) == 1


@pytest.mark.ci
def test_latest_returns_none_when_nothing_matches():
    assert _sessions.latest() is None
    assert _sessions.list_sessions() == []


# ── robustness: files are hand-editable ───────────────────────────────────────

@pytest.mark.ci
def test_load_tolerates_missing_frontmatter():
    path = _sessions.sessions_dir()
    path.mkdir(parents=True, exist_ok=True)
    f = path / "magic-broken-20260815-1000.md"
    f.write_text("## Steps\n- [x] one\n- [ ] two\n")

    loaded = _sessions.load(f)
    assert loaded is not None
    assert loaded.skill == "unknown"
    assert loaded.done_count == 1
    assert loaded.next_step.name == "two"


@pytest.mark.ci
def test_load_returns_none_for_missing_file():
    assert _sessions.load(_sessions.sessions_dir() / "nope.md") is None


@pytest.mark.ci
def test_hand_edited_checkbox_is_respected():
    """A human ticking a box in an editor must count as done."""
    s = _sessions.create("magic", "task", ["one", "two"])
    s.path.write_text(s.path.read_text().replace("- [ ] one", "- [x] one"))
    assert _sessions.load(s.path).done_count == 1


@pytest.mark.ci
def test_slugify_handles_punctuation_and_empty():
    # Hyphenated tokens count as one word, so this is 4 words, not 5.
    assert _sessions.slugify("Add retry-logic, to payments!") == "add-retry-logic-to-payments"
    assert _sessions.slugify("one two three four five") == "one-two-three-four"
    assert _sessions.slugify("") == "session"


# ── pruning ───────────────────────────────────────────────────────────────────

@pytest.mark.ci
def test_prune_keeps_unfinished_sessions_by_default():
    for i in range(5):
        s = _sessions.create("magic", f"task {i}", ["x"])
        if i < 3:
            s.finish()

    removed = _sessions.prune(keep=1)
    assert removed >= 1
    remaining = _sessions.list_sessions()
    assert all(s.status == "in_progress" for s in remaining if s.status != "completed")
    # The two unfinished ones must survive.
    assert len([s for s in remaining if s.status == "in_progress"]) == 2


@pytest.mark.ci
def test_prune_all_removes_unfinished_too():
    for i in range(4):
        _sessions.create("magic", f"task {i}", ["x"])
    _sessions.prune(keep=1, completed_only=False)
    assert len(_sessions.list_sessions()) == 1
