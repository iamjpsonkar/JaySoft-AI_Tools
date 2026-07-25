"""Tests for jsat.tools.prompt_optimizer. CI-safe: all offline, zero LLM calls."""
import pytest
from jsat._models import JSATConfig
from jsat.tools.prompt_optimizer import (
    ClassifyAgent, ContextAgent, ConstraintAgent,
    FewShotAgent, FormatAgent, CompressAgent,
    PromptOptimizer, _tok,
    RewriteResult, _score_rewrite,
    LLMRewriteAgent, LLMContextExpandAgent, LLMConstraintHardenAgent,
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


# ── RewriteResult dataclass ───────────────────────────────────────────────────

@pytest.mark.ci
def test_rewrite_result_fields():
    r = RewriteResult(prompt="rewritten", agent="rewrite", score=0.75, elapsed_ms=120.5)
    assert r.prompt == "rewritten"
    assert r.agent == "rewrite"
    assert r.score == 0.75
    assert r.elapsed_ms == 120.5


# ── _score_rewrite ────────────────────────────────────────────────────────────

@pytest.mark.ci
def test_score_rewrite_no_context_nodes():
    # No context nodes → coverage neutral (0.5)
    s = _score_rewrite("def process_refund(order_id: str) -> None:", "fix logger", [])
    assert 0.0 <= s <= 1.0

@pytest.mark.ci
def test_score_rewrite_with_matching_node():
    # Node name appears in rewrite → coverage = 1.0
    nodes = ["payments/service.py::process_refund"]
    s = _score_rewrite("ensure process_refund returns None when order_id is invalid",
                       "fix refund", nodes)
    assert s > 0.3  # should score reasonably given node name match

@pytest.mark.ci
def test_score_rewrite_higher_specificity_wins():
    # snake_case and camelCase tokens push specificity up
    generic = "please fix the issue with the thing in the code"
    specific = "ensure process_refund raises ValueError when order_id is None"
    s_generic = _score_rewrite(generic, "fix it", [])
    s_specific = _score_rewrite(specific, "fix it", [])
    assert s_specific > s_generic

@pytest.mark.ci
def test_score_rewrite_bloated_prompt_penalised():
    # Very long rewrite relative to offline prompt gets efficiency penalty
    short_offline = "fix logger"
    short_rewrite = "fix logger output"
    bloated_rewrite = ("fix logger output " + "x " * 500)
    s_short = _score_rewrite(short_rewrite, short_offline, [])
    s_bloat = _score_rewrite(bloated_rewrite, short_offline, [])
    assert s_short >= s_bloat

@pytest.mark.ci
def test_score_rewrite_returns_float_in_range():
    s = _score_rewrite("some rewrite here", "some prompt here", ["file.py::SomeClass"])
    assert isinstance(s, float)
    assert 0.0 <= s <= 1.0


# ── PromptResult new fields ───────────────────────────────────────────────────

@pytest.mark.ci
def test_prompt_result_rewrite_fields_default(optimizer):
    r = optimizer.optimize("improve retry logic")
    assert r.rewrite_applied is False
    assert r.rewrite_agents_run == 0
    assert r.rewrite_elapsed_ms == 0.0
    assert r.winning_agent is None

@pytest.mark.ci
def test_prompt_result_rewrite_skipped_no_ai(optimizer):
    # optimizer fixture has ai=None → rewrite should silently skip
    r = optimizer.optimize("improve retry logic", rewrite=True)
    assert r.rewrite_applied is False
    assert r.optimized_prompt  # offline prompt still returned

@pytest.mark.ci
def test_prompt_result_n_agents_skipped_no_ai(optimizer):
    r = optimizer.optimize("fix logger", n_agents=3)
    assert r.rewrite_applied is False
    assert r.rewrite_agents_run == 0

@pytest.mark.ci
def test_prompt_result_stages_no_rewrite(optimizer):
    r = optimizer.optimize("write a test")
    assert "rewrite" not in " ".join(r.stages_applied)


# ── LLM agent classes with mock AI ───────────────────────────────────────────

class MockAI:
    """Fake AI provider that returns a predictable rewrite."""
    available = True
    def is_available(self): return self.available
    def complete(self, prompt: str, max_tokens: int = 512) -> str:
        return f"ensure process_refund(order_id: str) raises ValueError when order_id is None"


class FailingAI:
    def is_available(self): return True
    def complete(self, *a, **kw): raise RuntimeError("AI unavailable")


class UnavailableAI:
    def is_available(self): return False
    def complete(self, *a, **kw): raise AssertionError("should not be called")


@pytest.mark.ci
def test_llm_rewrite_agent_returns_result():
    agent = LLMRewriteAgent()
    r = agent.run("fix logger in payments", [], MockAI())
    assert isinstance(r, RewriteResult)
    assert r.agent == "rewrite"
    assert r.prompt  # non-empty
    assert 0.0 <= r.score <= 1.0
    assert r.elapsed_ms >= 0

@pytest.mark.ci
def test_llm_rewrite_agent_fallback_on_error():
    agent = LLMRewriteAgent()
    offline = "fix logger in payments service"
    r = agent.run(offline, [], FailingAI())
    assert r.prompt == offline  # fallback to offline
    assert r.agent == "rewrite"

@pytest.mark.ci
def test_llm_context_expand_agent_returns_result():
    agent = LLMContextExpandAgent()
    r = agent.run("fix logger in payments", "fix logger", [], MockAI())
    assert isinstance(r, RewriteResult)
    assert r.agent == "context_expand"

@pytest.mark.ci
def test_llm_context_expand_agent_fallback_on_error():
    agent = LLMContextExpandAgent()
    offline = "fix logger"
    r = agent.run(offline, "fix logger", [], FailingAI())
    assert r.prompt == offline

@pytest.mark.ci
def test_llm_constraint_harden_agent_returns_result():
    agent = LLMConstraintHardenAgent()
    r = agent.run("fix the logger issue", [], MockAI())
    assert isinstance(r, RewriteResult)
    assert r.agent == "constraint_harden"

@pytest.mark.ci
def test_llm_constraint_harden_agent_fallback_on_error():
    agent = LLMConstraintHardenAgent()
    offline = "fix the logger issue"
    r = agent.run(offline, [], FailingAI())
    assert r.prompt == offline


# ── optimize() with mock AI — rewrite activated ───────────────────────────────

@pytest.fixture
def optimizer_with_ai(graph, cfg):
    return PromptOptimizer(graph=graph, cfg=cfg, ai=MockAI())


@pytest.mark.ci
def test_rewrite_applied_with_mock_ai(optimizer_with_ai):
    r = optimizer_with_ai.optimize("fix logger in payments", rewrite=True)
    assert r.rewrite_applied is True
    assert r.rewrite_agents_run == 1
    assert r.winning_agent == "rewrite"
    assert r.rewrite_elapsed_ms > 0

@pytest.mark.ci
def test_n_agents_3_with_mock_ai(optimizer_with_ai):
    r = optimizer_with_ai.optimize("fix logger in payments", n_agents=3)
    assert r.rewrite_applied is True
    assert r.rewrite_agents_run == 3
    assert r.winning_agent in ("rewrite", "context_expand", "constraint_harden")

@pytest.mark.ci
def test_n_agents_1_with_mock_ai(optimizer_with_ai):
    r = optimizer_with_ai.optimize("write a unit test for refund()", n_agents=1)
    assert r.rewrite_applied is True
    assert r.rewrite_agents_run == 1

@pytest.mark.ci
def test_rewrite_prompt_is_nonempty(optimizer_with_ai):
    r = optimizer_with_ai.optimize("fix the retry logic", rewrite=True)
    assert len(r.optimized_prompt) > 0

@pytest.mark.ci
def test_rewrite_stage_recorded_in_stages(optimizer_with_ai):
    r = optimizer_with_ai.optimize("fix logger", rewrite=True)
    assert any("rewrite" in s for s in r.stages_applied)

@pytest.mark.ci
def test_rewrite_timing_recorded(optimizer_with_ai):
    r = optimizer_with_ai.optimize("fix logger", rewrite=True)
    assert any(k.startswith("rewrite_") for k in r.agent_timings)

@pytest.mark.ci
def test_rewrite_offline_fields_still_set(optimizer_with_ai):
    r = optimizer_with_ai.optimize("fix logger", rewrite=True)
    assert r.task_type
    assert r.model_format
    assert r.tokens_before > 0

@pytest.mark.ci
def test_rewrite_n_agents_zero_is_noop(optimizer_with_ai):
    r = optimizer_with_ai.optimize("fix logger", n_agents=0)
    assert r.rewrite_applied is False

@pytest.mark.ci
def test_failing_ai_all_agents_fall_back(graph, cfg):
    opt = PromptOptimizer(graph=graph, cfg=cfg, ai=FailingAI())
    r = opt.optimize("fix logger", n_agents=3)
    # All agents fail → falls back to offline prompt
    assert r.rewrite_applied is False
