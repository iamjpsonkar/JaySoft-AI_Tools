"""jsat.tools.improve_submit — MAINTAINER-ONLY: turn a bundle into a PR.

This is the only module in the self-improvement feature that writes to a git
tree, so it is kept separate and is imported only by ``jsat improve --submit``.

It refuses to run unless it is inside the JSAT repository itself, so a developer
cannot accidentally apply an AI-generated patch to their own project.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import structlog
import typer

from jsat._cli_common import console, err

log = structlog.get_logger(__name__)


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=60, check=False
    )


def _guard_is_jsat_repo(repo: Path, github_repo: str) -> None:
    """Hard dev/maintainer separation — refuse to touch anything but JSAT."""
    remote = _git(["remote", "get-url", "origin"], repo)
    slug = github_repo.lower()
    if remote.returncode != 0 or slug not in remote.stdout.lower().replace(".git", ""):
        err.print(
            f"[red]Not the JSAT repository.[/] `--submit` only runs inside a "
            f"checkout of [bold]{github_repo}[/].\n"
            "This guard exists so an AI-generated patch can never be applied to "
            "your own project."
        )
        raise typer.Exit(1)

    pyproject = repo / "pyproject.toml"
    if not pyproject.exists() or 'name = "jsat"' not in pyproject.read_text(encoding="utf-8"):
        err.print("[red]pyproject.toml does not declare the jsat package.[/]")
        raise typer.Exit(1)

    status = _git(["status", "--porcelain"], repo)
    if status.stdout.strip():
        err.print("[red]Working tree is dirty.[/] Commit or stash first.")
        raise typer.Exit(1)


def _verify_hashes(repo: Path, files: list[dict], force: bool) -> None:
    """Detect drift between the reporter's installed version and this checkout."""
    drifted = []
    for entry in files:
        path = repo / entry["path"]
        if not path.exists():
            drifted.append(f"{entry['path']} (missing here)")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != entry.get("sha256"):
            drifted.append(f"{entry['path']} (changed since the report)")

    if drifted:
        console.print("[yellow]⚠ Source drift detected:[/]")
        for item in drifted:
            console.print(f"    {item}")
        if not force:
            err.print(
                "The patch was generated against different source. "
                "Re-run with [bold]--force[/] to try a 3-way apply anyway."
            )
            raise typer.Exit(1)


def submit_bundle(
    bundle_path: str, *, repo: str = ".", force: bool = False,
    run_tests: bool = True, yes: bool = False,
) -> None:
    """Apply a bundle in the JSAT checkout, run tests, and offer to open a PR."""
    bundle = Path(bundle_path).expanduser().resolve()
    manifest_path = bundle / "manifest.json"
    if not manifest_path.exists():
        err.print(f"[red]Not a bundle:[/] {bundle} (no manifest.json)")
        raise typer.Exit(1)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    repo_root = Path(repo).resolve()
    github_repo = "iamjpsonkar/JaySoft-AI_Tools"

    _guard_is_jsat_repo(repo_root, github_repo)

    if manifest.get("patch_status") != "validated":
        err.print(
            f"[red]Bundle patch status is[/] {manifest.get('patch_status')!r} — "
            "there is no validated patch to apply. Read analysis.md and fix by hand."
        )
        raise typer.Exit(1)

    _verify_hashes(repo_root, manifest.get("files", []), force)

    fingerprint = manifest.get("cluster", {}).get("fingerprint", "unknown")[:8]
    branch = f"jsat/improve-{fingerprint}"
    result = _git(["checkout", "-b", branch], repo_root)
    if result.returncode != 0:
        err.print(f"[red]Could not create branch {branch}:[/] {result.stderr.strip()}")
        raise typer.Exit(1)
    console.print(f"[green]✓[/] Branch [bold]{branch}[/]")

    applied = _git(["apply", "--3way", str(bundle / "patch.diff")], repo_root)
    if applied.returncode != 0:
        err.print(f"[red]Patch did not apply:[/] {applied.stderr.strip()}")
        _git(["checkout", "-"], repo_root)
        _git(["branch", "-D", branch], repo_root)
        raise typer.Exit(1)
    console.print("[green]✓[/] Patch applied")

    if run_tests:
        console.print("[dim]Running tests…[/]")
        tests = subprocess.run(
            ["python", "-m", "pytest", "-q"], cwd=str(repo_root),
            capture_output=True, text=True, timeout=900, check=False,
        )
        if tests.returncode != 0:
            err.print("[red]Tests failed — leaving the change uncommitted for review.[/]")
            console.print(tests.stdout[-2000:])
            raise typer.Exit(1)
        console.print("[green]✓[/] Tests pass")

    _git(["add", "-A"], repo_root)
    message = (
        f"fix: {manifest.get('cluster', {}).get('exc_type') or 'issue'} "
        f"reported by jsat improve ({fingerprint})\n\n"
        f"Occurrences: {manifest.get('cluster', {}).get('count')}\n"
        f"Reported against JSAT {manifest.get('jsat_version')}\n"
    )
    _git(["commit", "-m", message], repo_root)
    console.print("[green]✓[/] Committed")

    if not shutil.which("gh") or not yes:
        console.print(
            "\n[bold]To open the PR:[/]\n"
            f"  git push -u origin {branch}\n"
            f"  gh pr create --body-file {bundle / 'issue.md'}\n"
        )
        return

    _git(["push", "-u", "origin", branch], repo_root)
    subprocess.run(
        ["gh", "pr", "create", "--body-file", str(bundle / "issue.md")],
        cwd=str(repo_root), timeout=120, check=False,
    )
