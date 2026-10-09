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
    _codex_skill_owned_files,
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
    # SKILL.md AND every generated reference: the command bodies now live in
    # references/, so scanning SKILL.md alone would miss a leak.
    owned = _codex_skill_owned_files(skill_dir)
    assert owned, "generator produced no files"
    for rel, path in owned.items():
        content = path.read_text(encoding="utf-8")
        for leaked in (
            "Claude Code",
            "Claude session",
            "claude mcp list",
            "CLAUDE.md",
            "jsat connect claude",
        ):
            assert leaked not in content, f"{leaked!r} leaked untranslated into {rel}"


def _bundled_command_names() -> set[str]:
    return {
        p.stem.removeprefix("jsat-")
        for p in PKG_COMMANDS_DIR.glob("jsat-*.md")
        if p.stem != "jsat-help"
    }


@pytest.mark.ci
def test_codex_skill_is_split_into_dispatcher_and_references(tmp_path):
    skill_dir = tmp_path / "codex-skill"
    _write_codex_skill(skill_dir=skill_dir)
    skill_md = (skill_dir / "SKILL.md").read_text(encoding="utf-8")

    # The dispatcher must stay small: it used to embed every command body (~300 KB).
    assert len(skill_md.encode("utf-8")) < 20_000
    assert "references/commands/<COMMAND>.md" in skill_md
    assert "references/help.md" in skill_md

    expected = _bundled_command_names()
    assert expected, "no bundled commands found"
    generated = {p.stem for p in (skill_dir / "references" / "commands").glob("*.md")}
    assert generated == expected
    assert (skill_dir / "references" / "help.md").is_file()

    # Every command is in the catalog table, but no command body is embedded.
    for name in expected:
        assert f"| `$jsat {name}` |" in skill_md
        assert f"\n## {name}\n" not in skill_md
        assert (skill_dir / "references" / "commands" / f"{name}.md").stat().st_size > 0


@pytest.mark.ci
def test_codex_skill_output_is_idempotent(tmp_path):
    skill_dir = tmp_path / "codex-skill"
    _write_codex_skill(skill_dir=skill_dir)
    first = {rel: p.read_bytes() for rel, p in _codex_skill_owned_files(skill_dir).items()}
    _write_codex_skill(skill_dir=skill_dir)
    second = {rel: p.read_bytes() for rel, p in _codex_skill_owned_files(skill_dir).items()}
    assert first == second


@pytest.mark.ci
def test_codex_skill_removes_stale_command_refs_but_keeps_user_files(tmp_path):
    skill_dir = tmp_path / "codex-skill"
    _write_codex_skill(skill_dir=skill_dir)
    stale = skill_dir / "references" / "commands" / "removed-command.md"
    user_file = skill_dir / "references" / "my-notes.md"
    stale.write_text("old", encoding="utf-8")
    user_file.write_text("mine", encoding="utf-8")

    _write_codex_skill(skill_dir=skill_dir)

    assert not stale.exists()
    assert user_file.read_text(encoding="utf-8") == "mine"
    assert "references/my-notes.md" not in _codex_skill_owned_files(skill_dir)


@pytest.mark.ci
def test_test_atlas_command_is_registered_and_rendered(tmp_path):
    from jsat._cli_skills_data import _JSAT_SKILLS

    assert "jsat-test-atlas" in _JSAT_SKILLS
    description, body = _JSAT_SKILLS["jsat-test-atlas"]
    assert description.strip()
    # The comparability rules are what keep trend output honest; guard them.
    assert "NEVER 0" in body
    assert "COMPARABLE" in body

    commands_dir = tmp_path / "cmds"
    _write_jsat_dispatcher("global", commands_dir=commands_dir)
    dispatcher = (commands_dir / "jsat.md").read_text(encoding="utf-8")
    assert "| `/jsat test-atlas` |" in dispatcher
    assert "\n## test-atlas\n" in dispatcher


@pytest.mark.ci
def test_gcp_logs_is_a_narrow_registered_exception(tmp_path):
    from jsat._cli_skills_data import _JSAT_SKILLS

    assert "jsat-gcp-logs" in _JSAT_SKILLS
    _, body = _JSAT_SKILLS["jsat-gcp-logs"]
    # The Bash carve-out must stay read-only and explicit.
    assert "SCOPE" in body and "second" in body
    assert "gcloud logging read" in body
    assert "Never run any gcloud command that" in body
    # An injection-safe filter file, and an honest saturation/absence rule.
    assert '"$(cat <filter file>)"' in body
    assert "SATURATED" in body
    assert "no matching entry observed" in body
    # No private/organization-specific content ships in the generic command.
    for private in ("gringotts", "Gringotts", "Fynd", ".zshrc", "switch_context"):
        assert private not in body, f"{private!r} leaked into the generic command"

    # magic must never compose it, and the exception wording must name both.
    magic = _JSAT_SKILLS["jsat-magic"][1]
    assert "never selected or composed by magic" in magic
    internet = _JSAT_SKILLS["jsat-internet"][1]
    assert "gcp-logs" in internet
