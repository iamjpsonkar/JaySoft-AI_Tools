"""Tests for jsat.tools.prompt_optimizer. CI-safe: all offline, zero LLM calls."""
import pytest
from jsat._models import JSATConfig
from jsat.tools.prompt_optimizer import (
    ClassifyAgent, ContextAgent, ConstraintAgent,
    FewShotAgent, FormatAgent, CompressAgent,
    PromptOptimizer, _tok,
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
def cfg(): return JSATConfig()

@pytest.fixture
def optimizer(graph, cfg):
    return PromptOptimizer(graph=graph, cfg=cfg, ai=None)


# ── Token counter ─────────────────────────────────────────────────────────────

@pytest.mark.ci
def test_tok_empty(): assert _tok("") == 1
@pytest.mark.ci
def test_tok_single_word(): assert _tok("hello") >= 1
@pytest.mark.ci
def test_tok_grows_with_length():
    assert _tok("a b c d e f g h i j") > _tok("a b c")


# ── ClassifyAgent ─────────────────────────────────────────────────────────────

@pytest.mark.ci
def test_classify_code_gen():
    assert ClassifyAgent().run("write a function to validate payments").task_type == "code_gen"
@pytest.mark.ci
def test_classify_refactor():
    assert ClassifyAgent().run("refactor the retry logic").task_type == "refactor"
@pytest.mark.ci
def test_classify_debug():
    assert ClassifyAgent().run("why is this failing with a 500 error").task_type == "debug"
@pytest.mark.ci
def test_classify_test():
    assert ClassifyAgent().run("write a test for the refund function").task_type == "test"
@pytest.mark.ci
def test_classify_security():
    assert ClassifyAgent().run("find security vulnerabilities in auth").task_type == "security"
@pytest.mark.ci
def test_classify_question():
    assert ClassifyAgent().run("what does the payment service do").task_type == "question"
@pytest.mark.ci
def test_classify_fallback():
    assert ClassifyAgent().run("xyzzy quantum unicorn").task_type == "question"
@pytest.mark.ci
def test_classify_confidence_high():
    r = ClassifyAgent().run("write a function")
    assert r.confidence >= 0.8
@pytest.mark.ci
def test_classify_matched_keyword_present():
    r = ClassifyAgent().run("write a function")
    assert r.matched_keyword in "write a function"


# ── ContextAgent ──────────────────────────────────────────────────────────────

@pytest.mark.ci
def test_context_no_graph_entities(graph):
    r = ContextAgent(graph, depth=2, max_tokens=1000).run("improve retry logic")
    assert isinstance(r.text, str)
    assert isinstance(r.node_ids, list)
    assert r.tokens >= 0

@pytest.mark.ci
def test_context_empty_when_no_nodes(graph):
    r = ContextAgent(graph, depth=2, max_tokens=1000).run("xyzzy")
    assert r.text == "" or r.tokens == 0


# ── ConstraintAgent ───────────────────────────────────────────────────────────

@pytest.mark.ci
def test_constraint_no_kb(graph):
    r = ConstraintAgent(graph).run("code_gen")
    assert r.text == ""
    assert r.count == 0

@pytest.mark.ci
def test_constraint_returns_constraint_result(graph):
    from jsat.tools.prompt_optimizer import ConstraintResult
    r = ConstraintAgent(graph).run("security")
    assert isinstance(r, ConstraintResult)


# ── FewShotAgent ──────────────────────────────────────────────────────────────

@pytest.mark.ci
def test_fewshot_no_history_file(tmp_path):
    r = FewShotAgent(tmp_path / "nonexistent.jsonl").run("improve retry", "refactor", 3)
    assert r.examples == []

@pytest.mark.ci
def test_fewshot_empty_file(tmp_path):
    f = tmp_path / "h.jsonl"
    f.write_text("")
    r = FewShotAgent(f).run("improve retry", "refactor", 3)
    assert r.examples == []

@pytest.mark.ci
def test_fewshot_returns_top_k(tmp_path):
    import json
    from datetime import datetime, timezone
    f = tmp_path / "h.jsonl"
    lines = []
    for i in range(5):
        lines.append(json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "task_type": "refactor",
            "raw_input": f"refactor function {i}",
            "optimized_prompt": "...",
            "response": "done",
            "quality_score": 0.8,
        }))
    f.write_text("\n".join(lines))
    r = FewShotAgent(f).run("refactor payment retry", "refactor", 3)
    assert len(r.examples) <= 3

@pytest.mark.ci
def test_fewshot_filters_by_task_type(tmp_path):
    import json
    from datetime import datetime, timezone
    f = tmp_path / "h.jsonl"
    f.write_text(json.dumps({
        "ts": datetime.now(timezone.utc).isoformat(),
        "task_type": "code_gen",
        "raw_input": "write a function",
        "optimized_prompt": "...",
        "response": "done",
        "quality_score": 0.9,
    }))
    r = FewShotAgent(f).run("improve retry", "refactor", 3)
    assert r.examples == []  # wrong task_type filtered out


# ── FormatAgent ───────────────────────────────────────────────────────────────

@pytest.mark.ci
def test_format_claude_xml(graph):
    from jsat.tools.prompt_optimizer import ContextResult, ConstraintResult, FewShotResult
    r = FormatAgent().run("test task", "code_gen",
                          ContextResult(text="fn foo()", node_ids=[], tokens=5),
                          ConstraintResult(text="- use tenacity", count=1),
                          FewShotResult(examples=[], scores=[]),
                          None, "claude_cli", False)
    assert r.model_format == "xml"
    assert "<task>" in r.prompt
    assert "<system>" in r.prompt

@pytest.mark.ci
def test_format_gpt_markdown(graph):
    from jsat.tools.prompt_optimizer import ContextResult, ConstraintResult, FewShotResult
    r = FormatAgent().run("test task", "code_gen",
                          ContextResult(text="", node_ids=[], tokens=0),
                          ConstraintResult(text="", count=0),
                          FewShotResult(examples=[], scores=[]),
                          None, "openai", False)
    assert r.model_format == "markdown"
    assert "# Task" in r.prompt

@pytest.mark.ci
def test_format_plain_ollama(graph):
    from jsat.tools.prompt_optimizer import ContextResult, ConstraintResult, FewShotResult
    r = FormatAgent().run("test task", "code_gen",
                          ContextResult(text="", node_ids=[], tokens=0),
                          ConstraintResult(text="", count=0),
                          FewShotResult(examples=[], scores=[]),
                          None, "ollama", False)
    assert r.model_format == "plain"
    assert "test task" in r.prompt

@pytest.mark.ci
def test_format_output_spec_injected():
    from jsat.tools.prompt_optimizer import ContextResult, ConstraintResult, FewShotResult
    r = FormatAgent().run("task", "code_gen",
                          ContextResult(text="", node_ids=[], tokens=0),
                          ConstraintResult(text="", count=0),
                          FewShotResult(examples=[], scores=[]),
                          "Return only JSON.", "ollama", False)
    assert "Return only JSON." in r.prompt

@pytest.mark.ci
def test_format_cot_appended():
    from jsat.tools.prompt_optimizer import ContextResult, ConstraintResult, FewShotResult
    r = FormatAgent().run("task", "debug",
                          ContextResult(text="", node_ids=[], tokens=0),
                          ConstraintResult(text="", count=0),
                          FewShotResult(examples=[], scores=[]),
                          None, "openai", cot=True)
    assert "step by step" in r.prompt.lower()


# ── CompressAgent ─────────────────────────────────────────────────────────────

@pytest.mark.ci
def test_compress_no_op_when_under_budget():
    text = "short prompt"
    r = CompressAgent().run(text, max_tokens=10000)
    assert r.prompt == text
    assert r.passes == 0

@pytest.mark.ci
def test_compress_reduces_tokens():
    long_prompt = ("<output>\n" + "def foo():\n    pass\n" * 20 + "\n</output>\n") * 5
    orig = _tok(long_prompt)
    r = CompressAgent().run(long_prompt, max_tokens=50)
    assert r.final_tokens <= orig
    assert r.passes > 0

@pytest.mark.ci
def test_compress_preserves_task():
    text = "<task>\ndo the thing\n</task>\n" + "x " * 5000
    r = CompressAgent().run(text, max_tokens=100)
    assert "do the thing" in r.prompt


# ── PromptOptimizer integration ───────────────────────────────────────────────

@pytest.mark.ci
def test_optimizer_returns_prompt_result(optimizer):
    from jsat.tools.prompt_optimizer import PromptResult
    r = optimizer.optimize("improve the retry logic")
    assert isinstance(r, PromptResult)

@pytest.mark.ci
def test_optimizer_task_classified(optimizer):
    r = optimizer.optimize("write a test for refund()")
    assert r.task_type in ("test", "code_gen")

@pytest.mark.ci
def test_optimizer_tokens_after_set(optimizer):
    r = optimizer.optimize("explain the payment flow")
    assert r.tokens_after > 0

@pytest.mark.ci
def test_optimizer_no_context_flag(optimizer):
    r = optimizer.optimize("improve retry", no_context=True)
    assert r.context_nodes == []

@pytest.mark.ci
def test_optimizer_no_examples_flag(optimizer):
    r = optimizer.optimize("improve retry", no_examples=True)
    assert r.examples_used == 0

@pytest.mark.ci
def test_optimizer_stages_applied(optimizer):
    r = optimizer.optimize("write a function")
    assert "classify" in r.stages_applied
    assert "format" in r.stages_applied

@pytest.mark.ci
def test_optimizer_agent_timings_populated(optimizer):
    r = optimizer.optimize("refactor the retry logic")
    assert "classify" in r.agent_timings
    assert "format" in r.agent_timings

@pytest.mark.ci
def test_optimizer_model_format_set(optimizer):
    r = optimizer.optimize("fix the bug", ai_provider="claude_cli")
    assert r.model_format == "xml"

@pytest.mark.ci
def test_optimizer_cot_in_prompt(optimizer):
    r = optimizer.optimize("why is this broken", cot=True)
    assert "step by step" in r.optimized_prompt.lower()

@pytest.mark.ci
def test_optimizer_custom_format(optimizer):
    r = optimizer.optimize("task", output_format="Return ONLY YAML.")
    assert "Return ONLY YAML." in r.optimized_prompt

@pytest.mark.ci
def test_optimizer_raw_input_preserved(optimizer):
    raw = "improve the retry logic in payment service"
    r = optimizer.optimize(raw)
    assert r.raw_input == raw

@pytest.mark.ci
def test_optimizer_different_providers(optimizer):
    for provider, expected_fmt in [("anthropic","xml"), ("openai","markdown"), ("ollama","plain")]:
        r = optimizer.optimize("task", ai_provider=provider)
        assert r.model_format == expected_fmt
