"""Regression tests for jsat._cli_skills_data's generated-artifact bugs found
during a whole-project audit: the "## help" section duplication in both
jsat.md and the Codex SKILL.md, the flag-extraction heuristic matching
markdown dividers/prose, and Claude-specific text leaking untranslated into
the Codex skill. CI-safe: everything here runs against real bundled command
files, no network/AI calls.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from jsat._cli_skills_data import (
    _extract_flags_examples,
    _write_codex_skill,
    _write_jsat_dispatcher,
)

PKG_COMMANDS_DIR = Path(__file__).resolve().parent.parent / "jsat" / "commands"


@pytest.mark.ci
def test_extract_flags_examples_ignores_markdown_dividers():
    body = "\n".join([
        "Some intro text.",
        "---",
        "  --depth quick   → cap at 4 skills",
        "  --budget N      → explicit cap",
        "-- not a flag, just a prose dash",
        "---",
    ])
    flags_block, _ = _extract_flags_examples(body)
    assert "---" not in flags_block
    assert "--depth quick" in flags_block
    assert "--budget N" in flags_block
    assert "not a flag" not in flags_block


@pytest.mark.ci
def test_extract_flags_examples_falls_back_when_nothing_matches():
    flags_block, examples_block = _extract_flags_examples("No flags or examples here.")
    assert "no flags" in flags_block.lower()
    assert "/jsat <command>" in examples_block


@pytest.mark.ci
def test_extract_flags_examples_finds_examples_block():
    body = "\n".join([
        "Examples:",
        "  /jsat-foo bar",
        "  /jsat-foo --baz qux",
    ])
    _, examples_block = _extract_flags_examples(body)
    assert "/jsat-foo bar" in examples_block
    assert "/jsat-foo --baz qux" in examples_block


@pytest.mark.ci
def test_jsat_dispatcher_help_section_appears_exactly_once(tmp_path):
    out_dir = tmp_path / "commands"
    _write_jsat_dispatcher("local", commands_dir=out_dir)
    content = (out_dir / "jsat.md").read_text(encoding="utf-8")
    # Before this fix, the per-file embed loop re-embedded jsat-help.md's own
    # ~800-line generated body a second time under a second "## help" heading.
    assert content.count("\n## help\n") == 1


@pytest.mark.ci
def test_jsat_dispatcher_has_a_section_for_every_command(tmp_path):
    out_dir = tmp_path / "commands"
    _write_jsat_dispatcher("local", commands_dir=out_dir)
    content = (out_dir / "jsat.md").read_text(encoding="utf-8")
    names = [p.stem.removeprefix("jsat-") for p in sorted(PKG_COMMANDS_DIR.glob("jsat-*.md"))]
    missing = [n for n in names if f"\n## {n}\n" not in content]
    assert missing == []


@pytest.mark.ci
def test_jsat_help_md_regenerated_with_no_stale_command_names(tmp_path):
    out_dir = tmp_path / "commands"
    _write_jsat_dispatcher("local", commands_dir=out_dir)
    # jsat-help.md is regenerated on disk (in the bundled package dir) as a
    # side effect of building the dispatcher — read the live source of truth.
    help_content = (PKG_COMMANDS_DIR / "jsat-help.md").read_text(encoding="utf-8")
    for stale in ("### think", "### reflect", "### token-budget", "### knowledge-add"):
        assert stale not in help_content


@pytest.mark.ci
def test_codex_skill_help_section_not_embedded(tmp_path):
    skill_dir = tmp_path / "codex-skill"
    _write_codex_skill(skill_dir=skill_dir)
    content = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    # help's own body must never be embedded as a "## help" section in the
    # Codex skill either — it duplicated the whole file before this fix.
    assert "\n## help\n" not in content


@pytest.mark.ci
def test_codex_skill_has_no_claude_specific_leaks(tmp_path):
    skill_dir = tmp_path / "codex-skill"
    _write_codex_skill(skill_dir=skill_dir)
    content = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    for leaked in (
        "Claude Code",
        "Claude session",
        "claude mcp list",
        "CLAUDE.md",
        "jsat connect claude",
    ):
        assert leaked not in content, f"{leaked!r} leaked untranslated into the Codex skill"
