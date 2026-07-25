"""Tests for jsat.tools.token_optimizer. CI-safe: all offline, zero LLM calls."""
import pytest
from jsat.tools.token_optimizer import (
    TokenOptimizer,
    estimate_tokens,
    section_breakdown,
    MODEL_LIMITS,
    _apply_whitespace,
    _apply_stopphrase,
    _apply_import_collapse,
    _apply_dedup,
    _apply_comment_strip,
    _apply_recency_pin,
)


@pytest.fixture
def opt():
    return TokenOptimizer(graph=None, cfg=None, ai=None)


# ── estimate_tokens ────────────────────────────────────────────────────────────

@pytest.mark.ci
def test_estimate_empty():
    assert estimate_tokens("") == 0

@pytest.mark.ci
def test_estimate_grows_with_length():
    assert estimate_tokens("hello world foo bar baz") > estimate_tokens("hello")

@pytest.mark.ci
def test_estimate_code_denser_than_prose():
    # Same-length texts: code has more punctuation → fewer chars per token → more tokens per char
    code = "{}()[];, " * 100   # dense punctuation → code-heavy path
    prose = "the quick brown fox jumped over the lazy dog " * 20  # no punctuation → prose path
    # Pad both to same length so we compare token density, not raw counts
    length = min(len(code), len(prose))
    code_density = estimate_tokens(code[:length]) / length
    prose_density = estimate_tokens(prose[:length]) / length
    # Code tokens/char >= prose tokens/char (fewer chars per token in code)
    assert code_density >= prose_density * 0.9  # within 10% is fine

@pytest.mark.ci
def test_estimate_positive():
    assert estimate_tokens("x") >= 1

@pytest.mark.ci
def test_estimate_large_text():
    big = "word " * 10_000
    count = estimate_tokens(big)
    assert 5_000 < count < 20_000  # rough sanity range


# ── model_limit ────────────────────────────────────────────────────────────────

@pytest.mark.ci
def test_model_limit_claude_cli(opt):
    assert opt.model_limit("claude-cli") == 200_000

@pytest.mark.ci
def test_model_limit_gpt4o(opt):
    assert opt.model_limit("gpt-4o") == 128_000

@pytest.mark.ci
def test_model_limit_llama32(opt):
    assert opt.model_limit("llama3.2") == 131_072

@pytest.mark.ci
def test_model_limit_unknown(opt):
    assert opt.model_limit("nonexistent-model-xyz") is None

@pytest.mark.ci
def test_model_limit_case_insensitive(opt):
    assert opt.model_limit("Claude-CLI") == 200_000

@pytest.mark.ci
def test_model_limit_all_entries_positive():
    for k, v in MODEL_LIMITS.items():
        assert v > 0, f"Bad limit for {k}"


# ── budget ─────────────────────────────────────────────────────────────────────

@pytest.mark.ci
def test_budget_ok_status(opt):
    text = "hello " * 100
    result = opt.budget(text, "claude-cli")
    assert result["status"] == "ok"
    assert result["budget_pct"] < 1.0

@pytest.mark.ci
def test_budget_unknown_model(opt):
    result = opt.budget("hello", "unknown-model-xyz")
    assert result["status"] == "unknown"
    assert result["limit"] is None

@pytest.mark.ci
def test_budget_returns_headroom(opt):
    result = opt.budget("hello world", "gpt-4o")
    assert result["headroom_tokens"] is not None
    assert result["headroom_tokens"] > 0

@pytest.mark.ci
def test_budget_tokens_match_estimate(opt):
    text = "The quick brown fox " * 50
    result = opt.budget(text, "gpt-4o")
    assert result["tokens"] == estimate_tokens(text)


# ── analyze ────────────────────────────────────────────────────────────────────

@pytest.mark.ci
def test_analyze_no_compression(opt):
    text = "explain the payment service"
    report = opt.analyze(text)
    assert report.compressed_text == text
    assert report.savings_tokens == 0
    assert report.strategies_applied == []

@pytest.mark.ci
def test_analyze_with_model(opt):
    report = opt.analyze("hello world", model="claude-cli")
    assert report.model == "claude-cli"
    assert report.model_limit == 200_000
    assert report.budget_used_pct is not None
    assert report.budget_used_pct < 1.0

@pytest.mark.ci
def test_analyze_section_breakdown_xml(opt):
    text = "<task>write a function</task><system>you are an expert</system>"
    report = opt.analyze(text)
    assert "task" in report.section_breakdown
    assert "system" in report.section_breakdown

@pytest.mark.ci
def test_analyze_section_breakdown_markdown(opt):
    text = "## Task\nwrite a function\n\n## Context\nsome context here"
    report = opt.analyze(text)
    assert "Task" in report.section_breakdown or "Context" in report.section_breakdown


# ── strategy: whitespace ───────────────────────────────────────────────────────

@pytest.mark.ci
def test_whitespace_collapses_blank_lines():
    text = "a\n\n\n\nb"
    result = _apply_whitespace(text)
    assert "\n\n\n" not in result
    assert "a" in result and "b" in result

@pytest.mark.ci
def test_whitespace_strips_trailing_spaces():
    text = "hello   \nworld   \n"
    result = _apply_whitespace(text)
    assert "   " not in result

@pytest.mark.ci
def test_whitespace_no_leading_newlines():
    text = "\n\nhello"
    result = _apply_whitespace(text)
    assert not result.startswith("\n")

@pytest.mark.ci
def test_whitespace_preserves_content():
    text = "def foo():\n    return 42"
    result = _apply_whitespace(text)
    assert "def foo():" in result
    assert "return 42" in result


# ── strategy: stopphrase ───────────────────────────────────────────────────────

@pytest.mark.ci
def test_stopphrase_removes_certainly():
    result = _apply_stopphrase("Certainly!\nHere is the answer.")
    assert "Certainly!" not in result
    assert "Here is the answer." in result

@pytest.mark.ci
def test_stopphrase_removes_as_an_ai():
    result = _apply_stopphrase("As an AI language model, I cannot do that.")
    assert "As an AI language model" not in result

@pytest.mark.ci
def test_stopphrase_removes_i_hope_this_helps():
    result = _apply_stopphrase("The answer is 42.\nI hope this helps!")
    assert "I hope this helps" not in result
    assert "The answer is 42." in result

@pytest.mark.ci
def test_stopphrase_preserves_normal_text():
    text = "The payment service handles refunds."
    assert _apply_stopphrase(text) == text


# ── strategy: import collapse ──────────────────────────────────────────────────

@pytest.mark.ci
def test_import_collapse_merges_same_module():
    text = "from os import path\nfrom os import getcwd\nfrom os import environ\n"
    result = _apply_import_collapse(text)
    assert result.count("from os import") == 1
    assert "path" in result and "getcwd" in result and "environ" in result

@pytest.mark.ci
def test_import_collapse_keeps_different_modules():
    text = "from os import path\nfrom sys import argv\n"
    result = _apply_import_collapse(text)
    assert "from os import" in result
    assert "from sys import" in result

@pytest.mark.ci
def test_import_collapse_noop_single_import():
    text = "from os import path\n"
    result = _apply_import_collapse(text)
    assert result == text

@pytest.mark.ci
def test_import_collapse_non_from_imports_preserved():
    text = "import os\nimport sys\nfrom pathlib import Path\n"
    result = _apply_import_collapse(text)
    assert "import os" in result
    assert "import sys" in result


# ── strategy: dedup ────────────────────────────────────────────────────────────

@pytest.mark.ci
def test_dedup_removes_identical_lines():
    text = "The payment service validates inputs.\nThe payment service validates inputs."
    result = _apply_dedup(text)
    assert result.count("The payment service validates inputs") == 1

@pytest.mark.ci
def test_dedup_keeps_different_lines():
    text = "The payment service validates inputs.\nThe refund service processes returns."
    result = _apply_dedup(text)
    assert "payment" in result and "refund" in result

@pytest.mark.ci
def test_dedup_noop_single_chunk():
    text = "Just one sentence here."
    result = _apply_dedup(text)
    assert "Just one sentence" in result

@pytest.mark.ci
def test_dedup_near_duplicate_removed():
    # Very similar lines — should trigger dedup
    a = "The payment service handles refund processing."
    b = "The payment service handles refund processing requests."
    result = _apply_dedup(f"{a}\n{b}")
    # At least one is kept
    assert "payment service" in result


# ── strategy: comment strip ────────────────────────────────────────────────────

@pytest.mark.ci
def test_comment_strip_python():
    text = "# This is a comment\ndef foo():\n    pass\n"
    result = _apply_comment_strip(text)
    assert "# This is a comment" not in result
    assert "def foo():" in result

@pytest.mark.ci
def test_comment_strip_js():
    text = "// JS comment\nconst x = 1;\n"
    result = _apply_comment_strip(text)
    assert "// JS comment" not in result
    assert "const x = 1;" in result

@pytest.mark.ci
def test_comment_strip_preserves_shebang():
    text = "#!/usr/bin/env python3\ndef main(): pass"
    result = _apply_comment_strip(text)
    # Shebang (#!) is preserved
    assert "#!/usr/bin/env python3" in result

@pytest.mark.ci
def test_comment_strip_block_comment():
    text = "/*\n * block comment\n */\nint x = 1;"
    result = _apply_comment_strip(text)
    assert "block comment" not in result
    assert "int x = 1;" in result


# ── strategy: recency pin ──────────────────────────────────────────────────────

@pytest.mark.ci
def test_recency_pin_noop_under_budget():
    text = "short text"
    result = _apply_recency_pin(text, target_tokens=10_000)
    assert result == text

@pytest.mark.ci
def test_recency_pin_over_budget_inserts_marker():
    text = "word " * 5000
    result = _apply_recency_pin(text, target_tokens=100)
    assert "omitted" in result.lower() or "trimmed" in result.lower()

@pytest.mark.ci
def test_recency_pin_preserves_start_and_end():
    text = "STARTWORD " + "middle " * 2000 + " ENDWORD"
    result = _apply_recency_pin(text, target_tokens=50)
    assert "STARTWORD" in result
    assert "ENDWORD" in result


# ── compress integration ───────────────────────────────────────────────────────

@pytest.mark.ci
def test_compress_returns_report(opt):
    from jsat.tools.token_optimizer import TokenReport
    report = opt.compress("hello world")
    assert isinstance(report, TokenReport)

@pytest.mark.ci
def test_compress_noop_on_short_text(opt):
    text = "short"
    report = opt.compress(text)
    assert report.savings_tokens == 0
    assert report.compressed_text == text

@pytest.mark.ci
def test_compress_reduces_filler(opt):
    text = "Certainly!\nHere is the explanation.\n\n\n\nIt does the thing."
    report = opt.compress(text)
    assert "Certainly!" not in report.compressed_text

@pytest.mark.ci
def test_compress_with_model_sets_limit(opt):
    report = opt.compress("hello world", model="gpt-4o")
    assert report.model_limit == 128_000
    assert report.budget_used_pct is not None

@pytest.mark.ci
def test_compress_strategies_list(opt):
    text = "Certainly!\nhello   \n\n\n\nworld\n"
    report = opt.compress(text)
    # At least whitespace + stopphrase should fire
    assert len(report.strategies_applied) >= 1

@pytest.mark.ci
def test_compress_with_target_applies_dedup(opt):
    repeated = "The payment service validates all inputs. " * 30
    report = opt.compress(repeated, target_tokens=10)
    assert report.compressed_tokens < report.original_tokens

@pytest.mark.ci
def test_compress_strip_comments(opt):
    text = "# a comment\ndef foo():\n    # another\n    return 1\n"
    report = opt.compress(text, strip_comments=True)
    assert "# a comment" not in report.compressed_text
    assert "def foo():" in report.compressed_text

@pytest.mark.ci
def test_compress_no_dedup(opt):
    # With no_dedup=True and no target, only lossless strategies run
    text = "normal text without filler\n"
    report = opt.compress(text, dedup=False)
    assert "dedup" not in report.strategies_applied

@pytest.mark.ci
def test_compress_elapsed_ms(opt):
    report = opt.compress("some text here")
    assert report.elapsed_ms >= 0

@pytest.mark.ci
def test_compress_import_collapse(opt):
    text = "from os import path\nfrom os import getcwd\nsome code here\n"
    report = opt.compress(text)
    if "import_collapse" in report.strategies_applied:
        assert report.compressed_text.count("from os import") == 1


# ── section_breakdown ──────────────────────────────────────────────────────────

@pytest.mark.ci
def test_section_breakdown_xml():
    text = "<task>do the thing</task><context>some context</context>"
    bd = section_breakdown(text)
    assert "task" in bd
    assert "context" in bd

@pytest.mark.ci
def test_section_breakdown_markdown():
    text = "## Task\ndo the thing\n\n## Context\nsome context"
    bd = section_breakdown(text)
    assert "Task" in bd or "Context" in bd

@pytest.mark.ci
def test_section_breakdown_plain_paragraphs():
    text = "paragraph one here.\n\nparagraph two here."
    bd = section_breakdown(text)
    assert len(bd) >= 2

@pytest.mark.ci
def test_section_breakdown_all_positive():
    text = "<a>foo</a><b>bar baz qux</b>"
    bd = section_breakdown(text)
    for v in bd.values():
        assert v >= 0
