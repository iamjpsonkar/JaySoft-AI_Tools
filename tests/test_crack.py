"""Tests for jsat.tools.crack — CI-safe: all offline, zero LLM calls."""
import pytest
from pathlib import Path
from jsat.tools.crack import (
    CrackTool, CrackStatement, CrackResult,
    _ROLE_PROMPTS, _DEFAULT_ROLES, _format_history,
    _build_agent_prompt, _offline_statement, _render_markdown,
)


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
def graph(): return NoOpGraph()

@pytest.fixture
def cfg():
    from jsat._models import JSATConfig
    return JSATConfig()

@pytest.fixture
def crack(graph, cfg):
    return CrackTool(graph=graph, cfg=cfg, ai=None)


# ── Data models ────────────────────────────────────────────────────────────────

@pytest.mark.ci
def test_crack_statement_fields():
    s = CrackStatement(role="architect", round_num=1, text="design idea", elapsed_ms=50.0)
    assert s.role == "architect"
    assert s.round_num == 1
    assert s.elapsed_ms == 50.0

@pytest.mark.ci
def test_crack_result_fields():
    r = CrackResult(
        task="test task", roles=["architect"], rounds_run=1,
        statements=[], synthesis="done", output_path=None,
        elapsed_ms=100.0, ai_available=False,
    )
    assert r.task == "test task"
    assert r.ai_available is False


# ── Role prompts ───────────────────────────────────────────────────────────────

@pytest.mark.ci
def test_all_default_roles_have_prompts():
    for role in _DEFAULT_ROLES:
        assert role in _ROLE_PROMPTS, f"Missing prompt for role: {role}"
        assert len(_ROLE_PROMPTS[role]) > 50

@pytest.mark.ci
def test_moderator_prompt_contains_structure():
    prompt = _ROLE_PROMPTS["moderator"]
    assert "Agreed" in prompt
    assert "Disputed" in prompt
    assert "action" in prompt.lower()

@pytest.mark.ci
def test_six_default_roles():
    assert len(_DEFAULT_ROLES) == 6
    assert "moderator" in _DEFAULT_ROLES


# ── format_history ─────────────────────────────────────────────────────────────

@pytest.mark.ci
def test_format_history_empty():
    result = _format_history([])
    assert "No previous" in result

@pytest.mark.ci
def test_format_history_with_statements():
    stmts = [
        CrackStatement("architect", 1, "Design proposal here.", 10.0),
        CrackStatement("security", 1, "Security concerns here.", 12.0),
    ]
    result = _format_history(stmts)
    assert "architect" in result.upper() or "ARCHITECT" in result
    assert "Round 1" in result

@pytest.mark.ci
def test_format_history_multiple_rounds():
    stmts = [
        CrackStatement("architect", 1, "Round 1 proposal.", 10.0),
        CrackStatement("architect", 2, "Round 2 response.", 10.0),
    ]
    result = _format_history(stmts)
    assert "Round 1" in result
    assert "Round 2" in result

@pytest.mark.ci
def test_format_history_truncates_long_text():
    long_text = "x" * 1000
    stmts = [CrackStatement("architect", 1, long_text, 0.0)]
    result = _format_history(stmts, max_chars_per=100)
    assert len(result) < 500   # much shorter than original


# ── build_agent_prompt ─────────────────────────────────────────────────────────

@pytest.mark.ci
def test_build_agent_prompt_round1():
    prompt = _build_agent_prompt("architect", "redesign retry", "", "No prev.", 1, 3)
    assert "architect" in prompt.lower() or "ARCHITECT" in prompt
    assert "redesign retry" in prompt
    assert "Round 1" in prompt

@pytest.mark.ci
def test_build_agent_prompt_moderator_last():
    prompt = _build_agent_prompt("moderator", "task", "", "history", 3, 3)
    assert "synthesis" in prompt.lower() or "moderator" in prompt.lower()

@pytest.mark.ci
def test_build_agent_prompt_includes_context():
    ctx = "class PaymentService:\n    def process(self): ..."
    prompt = _build_agent_prompt("implementer", "task", ctx, "", 1, 3)
    assert "PaymentService" in prompt

@pytest.mark.ci
def test_build_agent_prompt_round2_says_respond():
    prompt = _build_agent_prompt("skeptic", "task", "", "prev history", 2, 3)
    assert "respond" in prompt.lower() or "round 2" in prompt.lower()


# ── offline_statement ──────────────────────────────────────────────────────────

@pytest.mark.ci
def test_offline_statement_returns_statement():
    s = _offline_statement("architect", 1, "redesign retry", "some context")
    assert isinstance(s, CrackStatement)
    assert s.role == "architect"
    assert s.round_num == 1
    assert s.text

@pytest.mark.ci
def test_offline_statement_all_roles():
    for role in _DEFAULT_ROLES:
        s = _offline_statement(role, 1, "test task", "")
        assert s.text, f"Empty offline statement for {role}"


# ── render_markdown ────────────────────────────────────────────────────────────

@pytest.mark.ci
def test_render_markdown_has_title():
    stmts = [CrackStatement("architect", 1, "Design idea.", 10.0)]
    md = _render_markdown("redesign payment", stmts, "Final synthesis.")
    assert "redesign payment" in md
    assert "Final Synthesis" in md

@pytest.mark.ci
def test_render_markdown_includes_synthesis():
    stmts = [CrackStatement("architect", 1, "Design idea.", 10.0)]
    synthesis = "✅ Agreed: use tenacity\n🎯 Action: refactor retry"
    md = _render_markdown("task", stmts, synthesis)
    assert "tenacity" in md
    assert "Final Synthesis" in md

@pytest.mark.ci
def test_render_markdown_has_round_headers():
    stmts = [
        CrackStatement("architect", 1, "R1.", 0.0),
        CrackStatement("architect", 2, "R2.", 0.0),
    ]
    md = _render_markdown("task", stmts, "")
    assert "Round 1" in md
    assert "Round 2" in md


# ── CrackTool.run() — offline (no AI) ────────────────────────────────────────

@pytest.mark.ci
def test_crack_run_offline_returns_result(crack):
    result = crack.run("should we use async or sync webhooks", rounds=2)
    assert isinstance(result, CrackResult)
    assert result.ai_available is False

@pytest.mark.ci
def test_crack_run_offline_all_roles(crack):
    result = crack.run("redesign retry", rounds=1)
    roles_in_result = {s.role for s in result.statements}
    # All 6 default roles should have statements
    for role in _DEFAULT_ROLES:
        assert role in roles_in_result, f"Missing role: {role}"

@pytest.mark.ci
def test_crack_run_offline_correct_round_count(crack):
    result = crack.run("test task", rounds=2)
    assert result.rounds_run == 2
    rounds_in_statements = {s.round_num for s in result.statements}
    assert 1 in rounds_in_statements
    assert 2 in rounds_in_statements

@pytest.mark.ci
def test_crack_run_offline_subset_roles(crack):
    result = crack.run("test task", roles=["architect", "security"], rounds=1)
    roles_in_result = {s.role for s in result.statements}
    assert "architect" in roles_in_result
    assert "security" in roles_in_result
    assert "moderator" in roles_in_result   # always added

@pytest.mark.ci
def test_crack_run_offline_writes_file(crack, tmp_path):
    out = tmp_path / "output.md"
    result = crack.run("test task", rounds=1, output_file=str(out))
    assert out.exists()
    assert result.output_path == str(out)
    content = out.read_text()
    assert "test task" in content

@pytest.mark.ci
def test_crack_run_offline_writes_jsat_dir(crack, tmp_path):
    result = crack.run("test task", rounds=1, repo_path=tmp_path)
    assert result.output_path is not None
    assert Path(result.output_path).exists()
    assert ".jsat/crack" in result.output_path

@pytest.mark.ci
def test_crack_elapsed_ms_positive(crack):
    result = crack.run("test task", rounds=1)
    assert result.elapsed_ms >= 0

@pytest.mark.ci
def test_crack_task_preserved(crack):
    task = "unique task description xyz"
    result = crack.run(task, rounds=1)
    assert result.task == task

@pytest.mark.ci
def test_crack_single_round(crack):
    result = crack.run("minimal test", rounds=1)
    assert result.rounds_run == 1
    assert len(result.statements) == len(_DEFAULT_ROLES)  # 6 statements
