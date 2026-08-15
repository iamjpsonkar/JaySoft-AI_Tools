"""Tests for jsat.tools.improve_submit — the maintainer-only guards.

The point of these tests is that `--submit` must be *impossible* to run by accident
outside the JSAT repository: it is the only part of the self-improvement feature that
writes to a git tree.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
import typer

from jsat.tools.improve_submit import submit_bundle


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=False)


def _make_repo(path: Path, *, remote: str, pyproject_name: str = "jsat") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(["init", "-q"], path)
    _git(["config", "user.email", "t@example.com"], path)
    _git(["config", "user.name", "Test"], path)
    _git(["remote", "add", "origin", remote], path)
    (path / "pyproject.toml").write_text(f'[project]\nname = "{pyproject_name}"\n')
    (path / "jsat").mkdir(exist_ok=True)
    (path / "jsat" / "demo.py").write_text("def f():\n    return 1\n")
    _git(["add", "-A"], path)
    _git(["commit", "-q", "-m", "init"], path)
    return path


def _make_bundle(path: Path, *, status="validated", files=None) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "bundle_id": "abcd1234-20260815T090000Z",
        "jsat_version": "0.4.7",
        "patch_status": status,
        "cluster": {"fingerprint": "abcd1234deadbeef", "exc_type": "IndexNotFound", "count": 3},
        "files": files if files is not None else [],
    }
    (path / "manifest.json").write_text(json.dumps(manifest))
    (path / "patch.diff").write_text(
        "--- a/jsat/demo.py\n+++ b/jsat/demo.py\n@@ -1,2 +1,2 @@\n"
        " def f():\n-    return 1\n+    return 42\n"
    )
    (path / "issue.md").write_text("### body\n")
    return path


# ── the repository guard ──────────────────────────────────────────────────────

@pytest.mark.ci
def test_refuses_outside_the_jsat_repository(tmp_path):
    """The core guard: an AI patch must never land in someone else's project."""
    repo = _make_repo(tmp_path / "someone-elses-app",
                      remote="https://github.com/acme/private-app.git")
    bundle = _make_bundle(tmp_path / "bundle")

    with pytest.raises(typer.Exit) as exc:
        submit_bundle(str(bundle), repo=str(repo))
    assert exc.value.exit_code == 1
    # The file must be untouched.
    assert "return 1" in (repo / "jsat" / "demo.py").read_text()


@pytest.mark.ci
def test_refuses_when_pyproject_is_not_jsat(tmp_path):
    repo = _make_repo(tmp_path / "fork", remote="https://github.com/iamjpsonkar/JaySoft-AI_Tools.git",
                      pyproject_name="not-jsat")
    bundle = _make_bundle(tmp_path / "bundle")

    with pytest.raises(typer.Exit):
        submit_bundle(str(bundle), repo=str(repo))


@pytest.mark.ci
def test_refuses_on_dirty_tree(tmp_path):
    repo = _make_repo(tmp_path / "jsat", remote="https://github.com/iamjpsonkar/JaySoft-AI_Tools.git")
    (repo / "jsat" / "demo.py").write_text("uncommitted change\n")
    bundle = _make_bundle(tmp_path / "bundle")

    with pytest.raises(typer.Exit):
        submit_bundle(str(bundle), repo=str(repo))


# ── bundle validation ─────────────────────────────────────────────────────────

@pytest.mark.ci
def test_rejects_missing_bundle(tmp_path):
    repo = _make_repo(tmp_path / "jsat", remote="https://github.com/iamjpsonkar/JaySoft-AI_Tools.git")
    with pytest.raises(typer.Exit):
        submit_bundle(str(tmp_path / "nope"), repo=str(repo))


@pytest.mark.ci
@pytest.mark.parametrize("status", ["no_ai", "no_patch", "did_not_apply", "ai_error"])
def test_rejects_bundles_without_a_validated_patch(status, tmp_path):
    repo = _make_repo(tmp_path / "jsat", remote="https://github.com/iamjpsonkar/JaySoft-AI_Tools.git")
    bundle = _make_bundle(tmp_path / f"bundle-{status}", status=status)

    with pytest.raises(typer.Exit):
        submit_bundle(str(bundle), repo=str(repo))


# ── drift detection ───────────────────────────────────────────────────────────

@pytest.mark.ci
def test_hash_drift_requires_force(tmp_path):
    """The reporter's installed source differed from this checkout."""
    repo = _make_repo(tmp_path / "jsat", remote="https://github.com/iamjpsonkar/JaySoft-AI_Tools.git")
    bundle = _make_bundle(
        tmp_path / "bundle",
        files=[{"path": "jsat/demo.py", "sha256": "0" * 64, "size": 10}],
    )

    with pytest.raises(typer.Exit):
        submit_bundle(str(bundle), repo=str(repo))


@pytest.mark.ci
def test_matching_hashes_pass_the_drift_check(tmp_path):
    """A bundle whose hashes match proceeds past the guards."""
    repo = _make_repo(tmp_path / "jsat", remote="https://github.com/iamjpsonkar/JaySoft-AI_Tools.git")
    digest = hashlib.sha256((repo / "jsat" / "demo.py").read_bytes()).hexdigest()
    bundle = _make_bundle(
        tmp_path / "bundle",
        files=[{"path": "jsat/demo.py", "sha256": digest, "size": 20}],
    )

    # run_tests=False: this synthetic repo has no test suite.
    submit_bundle(str(bundle), repo=str(repo), run_tests=False, yes=False)

    assert "return 42" in (repo / "jsat" / "demo.py").read_text()
    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(repo),
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    assert branch == "jsat/improve-abcd1234"


@pytest.mark.ci
def test_does_not_push_without_yes(tmp_path, capsys):
    """Without --yes the command prints the push/PR commands instead of running them."""
    repo = _make_repo(tmp_path / "jsat", remote="https://github.com/iamjpsonkar/JaySoft-AI_Tools.git")
    digest = hashlib.sha256((repo / "jsat" / "demo.py").read_bytes()).hexdigest()
    bundle = _make_bundle(
        tmp_path / "bundle",
        files=[{"path": "jsat/demo.py", "sha256": digest, "size": 20}],
    )

    submit_bundle(str(bundle), repo=str(repo), run_tests=False, yes=False)

    output = capsys.readouterr().out
    assert "git push" in output
    assert "gh pr create" in output
