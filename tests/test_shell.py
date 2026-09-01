"""Tests for jsat.tools.shell. CI-safe: writes only to tmp_path profile files."""
from __future__ import annotations

import shlex

import pytest

from jsat.tools.shell import JSATShell


class FakeJSAT:
    """Minimal stand-in for jsat._core.JSAT — shell only touches it defensively."""
    _cfg = object()

    def _get_graph(self):
        raise RuntimeError("no graph in tests")

    def active_ai_label(self):
        return "test"


@pytest.fixture
def shell():
    return JSATShell(FakeJSAT())


@pytest.mark.ci
def test_save_key_escapes_shell_metacharacters(shell, tmp_path, monkeypatch):
    """A key containing shell metacharacters must not be able to inject commands.

    Regression for: _save_key_to_profile() previously interpolated the raw key
    into an f-string with only double quotes around it, e.g.
    f'export VAR="{key}"'. A key like '"; touch /tmp/pwned; echo "' would close
    the quoted string and inject an arbitrary command that runs on every login.
    """
    profile = tmp_path / ".zshrc"
    profile.write_text("# existing profile\n")
    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    malicious_key = '"; touch /tmp/pwned; echo "'
    shell._save_key_to_profile("SOME_API_KEY", malicious_key)

    written = profile.read_text()
    export_line = next(line for line in written.splitlines() if "SOME_API_KEY" in line)

    # Proof of correctness: parsing the line as shell tokens (comments stripped,
    # exactly as a real shell sourcing this profile would do) must round-trip
    # to a single "VAR=value" token carrying the exact original key — i.e. the
    # shell treats it as one opaque string, not as quote-closing + injected
    # commands. If the key were unescaped, `shlex.split` would instead produce
    # several tokens (the injected "touch", "/tmp/pwned", "echo", ... words).
    tokens = shlex.split(export_line, comments=True)
    assert tokens == ["export", f"SOME_API_KEY={malicious_key}"]


@pytest.mark.ci
def test_save_key_simple_value_round_trips(shell, tmp_path, monkeypatch):
    profile = tmp_path / ".zshrc"
    profile.write_text("")
    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    shell._save_key_to_profile("PLAIN_KEY", "sk-abc123")

    written = profile.read_text()
    export_line = next(line for line in written.splitlines() if "PLAIN_KEY" in line)
    tokens = shlex.split(export_line, comments=True)
    assert tokens == ["export", "PLAIN_KEY=sk-abc123"]
