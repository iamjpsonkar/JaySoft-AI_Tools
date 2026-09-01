"""Regression test for Bug 2 (Critical, security): shell command injection in
`jsat index --watch`.

`cmd_index`'s --watch branch builds a `find ... | entr -c ...` pipeline and runs
it with `subprocess.run(..., shell=True)`, interpolating the resolved repo path
directly into the string. A directory whose name contains shell metacharacters
(a legal POSIX filename, e.g. "repo; touch pwned") must not be able to terminate
the intended command early and run arbitrary code.

We don't invoke `sh` for real (entr/environment may not be present in CI); instead
we intercept `subprocess.run` and assert the exact command string it was given
treats the malicious path as a single inert token, using shlex.split to confirm
there's no unintended token boundary at the injected metacharacter.
"""
from __future__ import annotations

import shlex
import shutil
import subprocess

import pytest
from typer.testing import CliRunner

from jsat.cli import app

runner = CliRunner()


@pytest.mark.ci
def test_watch_quotes_malicious_target_path(monkeypatch, tmp_path):
    import jsat._cli_index as index_mod

    captured: dict[str, object] = {}

    # `cmd_index` does `import shutil` / `import subprocess` locally inside the
    # --watch branch — those bind to the *same* module objects in sys.modules,
    # so patching the real `shutil`/`subprocess` modules here affects it too.
    # --watch is gated on `shutil.which("entr")` before the command string is
    # even built; fake its presence so the test exercises the string-building
    # logic regardless of whether entr happens to be installed in CI.
    real_which = shutil.which
    monkeypatch.setattr(
        shutil, "which",
        lambda name: "/usr/local/bin/entr" if name == "entr" else real_which(name),
    )

    def fake_run(command, shell=False):
        captured["command"] = command
        captured["shell"] = shell

    monkeypatch.setattr(subprocess, "run", fake_run)

    class FakeResult:
        incremental = False
        files_skipped = 0
        nodes_indexed = 1
        edges_indexed = 1

    monkeypatch.setattr(index_mod, "_jsat", lambda repo: type(
        "FakeJSAT", (), {"index": staticmethod(lambda **kw: FakeResult())}
    )())

    target = tmp_path / "repo; touch pwned"
    target.mkdir()

    result = runner.invoke(app, ["index", str(target), "--watch"])
    assert result.exit_code == 0

    command = captured["command"]
    assert captured["shell"] is True

    # The malicious path must appear as a single shlex token, not split into
    # separate shell commands. shlex.split() is a stand-in for what `sh -c`
    # would actually tokenize; if the path leaked in unquoted, this would either
    # raise (unbalanced quoting) or split "repo" and ";" into separate tokens.
    tokens = shlex.split(command)
    assert str(target) in tokens, (
        "the target path must round-trip as one token when parsed by a shell "
        f"tokenizer; got tokens={tokens!r} from command={command!r}"
    )
    # Sanity: the injected `; touch pwned` must not appear as a bare, unquoted
    # command separator in the raw string outside of the quoted path.
    assert "touch pwned" not in command.replace(shlex.quote(str(target)), "")
