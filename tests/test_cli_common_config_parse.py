"""Regression tests for Bug 4 (High): config corruption on malformed JSON.

`_read_json()` used to silently swallow `JSONDecodeError` and return `{}`. Every
`jsat connect <tool>` command then merged its own entry into that empty dict and
called `_write_json`, destroying the user's existing-but-merely-malformed (e.g.
trailing comma) config file. `_read_json` now raises `ConfigParseError`, and every
write-path call site uses `_read_json_or_abort`, which prints a clear error and
exits instead of silently overwriting.
"""
from __future__ import annotations

import pytest
from typer.testing import CliRunner

from jsat._cli_common import ConfigParseError, _read_json, _read_json_or_abort
from jsat.cli import app

runner = CliRunner()

# trailing comma after "other" entry makes this invalid JSON
_MALFORMED_JSON = '{\n  "mcpServers": {\n    "other": {"command": "foo"},\n  }\n}\n'


@pytest.mark.ci
def test_read_json_raises_config_parse_error_on_malformed_file(tmp_path):
    bad = tmp_path / "settings.json"
    bad.write_text(_MALFORMED_JSON, encoding="utf-8")

    with pytest.raises(ConfigParseError):
        _read_json(bad)


@pytest.mark.ci
def test_read_json_or_abort_exits_cleanly_instead_of_raising(tmp_path, capsys):
    import typer

    bad = tmp_path / "settings.json"
    bad.write_text(_MALFORMED_JSON, encoding="utf-8")

    with pytest.raises(typer.Exit):
        _read_json_or_abort(bad)


@pytest.mark.ci
def test_connect_claude_does_not_wipe_malformed_existing_config(tmp_path, monkeypatch):
    """The core regression: a pre-existing malformed config file must survive a
    `jsat connect claude` run untouched, rather than being silently replaced with
    a file containing only the newly added jsat entry."""
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(_MALFORMED_JSON, encoding="utf-8")
    original = settings_path.read_text(encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["connect", "claude", "--repo", str(tmp_path)])

    assert result.exit_code != 0
    # The original (malformed-but-recoverable) content must be preserved, not
    # silently overwritten with a fresh file containing only the jsat entry.
    assert settings_path.read_text(encoding="utf-8") == original


@pytest.mark.ci
def test_connect_remove_does_not_wipe_malformed_existing_config(tmp_path, monkeypatch):
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(_MALFORMED_JSON, encoding="utf-8")
    original = settings_path.read_text(encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["connect", "remove"])

    assert result.exit_code != 0
    assert settings_path.read_text(encoding="utf-8") == original
