"""Regression test for Bug 3 (Critical, live crash): `jsat knowledge-ingest` crashed
unconditionally, even in --dry-run.

`cmd_knowledge_ingest` accessed `r.source_file.name` in its preview-print loop, but
`IngestRecord` (jsat/tools/knowledge_ingest.py) has no `source_file` attribute — it
has `source_path`. This was an unconditional AttributeError before ingestion even
started, so --dry-run (meant to be side-effect-free) always crashed.
"""
from __future__ import annotations

import pytest
from typer.testing import CliRunner

from jsat.cli import app

runner = CliRunner()


@pytest.mark.ci
def test_knowledge_ingest_dry_run_does_not_crash(tmp_path):
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text(
        "# Project notes\n\nThis service does X.\n\n"
        "## Gotchas\n\nWatch out for Y when deploying.\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["knowledge-ingest", str(tmp_path), "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "AttributeError" not in result.output
    assert "source_file" not in result.output
    assert "not ingesting" in result.output.lower()
    # The preview line should show the actual source filename.
    assert "CLAUDE.md" in result.output


@pytest.mark.ci
def test_knowledge_ingest_dry_run_reports_no_files_found_gracefully(tmp_path):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    result = runner.invoke(app, ["knowledge-ingest", str(empty_dir), "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "No files found" in result.output
