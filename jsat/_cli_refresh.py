"""
jsat._cli_refresh — `jsat refresh`: check for a newer version and re-sync
the bundled skill documents into every connected AI tool.

Refresh is the "sync what changed" counterpart to `jsat connect`. It never
installs into a tool that is not connected, never writes to the installed
package's own command files (everything is diffed against a throwaway copy),
and degrades gracefully when PyPI is unreachable — a version check failure
is a note, never a crash.
"""
from __future__ import annotations

import json
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import typer

from ._cli_common import _read_json, _write_json, app, console, err

__all__: list[str] = []

_SKILL_TOOLS: tuple[str, ...] = ("claude", "codex", "opencode", "bob", "continue")
# Tools whose skill targets exist at BOTH project and global scope.
_SCOPED_TOOLS: tuple[str, ...] = ("claude", "opencode", "bob")

_PYPI_JSON = "https://pypi.org/pypi/jsat/json"
_TOOL_LABELS = {
    "claude": "Claude Code",
    "codex": "Codex",
    "opencode": "OpenCode",
    "bob": "Bob",
    "continue": "Continue.dev",
}


@dataclass
class RefreshLine:
    tool: str
    scope: str
    status: str  # ok | synced | would-sync | skipped | error
    added: int = 0
    modified: int = 0
    removed: int = 0
    note: str = ""


@dataclass
class RefreshResult:
    version: str | None = None
    version_note: str = ""
    update_available: bool = False
    lines: list[RefreshLine] = field(default_factory=list)


def _version_tuple(version: str) -> tuple[int, int, int]:
    """Coarse PEP 440 compare: take the first three dotted integer parts and
    ignore pre/post/local identifiers, so '0.4.21' > '0.4.20rc1' and a
    pre-release is treated as its release for the upgrade hint."""
    out: list[int] = []
    for part in re.split(r"[.\-+]", version)[:3]:
        m = re.match(r"\d+", part)
        out.append(int(m.group()) if m else 0)
    while len(out) < 3:
        out.append(0)
    return out[0], out[1], out[2]


def _pypi_version() -> tuple[str, str | None, str]:
    """Return (installed, latest, note). Best-effort; never raises.

    ``latest`` is None when PyPI cannot be reached or answers badly. The note
    explains why, so the human sees "no check" rather than a silent skip.
    """
    import urllib.request

    try:
        from jsat import __version__
    except Exception:
        __version__ = "unknown"
    try:
        req = urllib.request.Request(
            _PYPI_JSON,
            headers={"User-Agent": f"jsat-refresh/{__version__}"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status != 200:
                raise OSError(f"PyPI returned HTTP {resp.status}")
            latest = json.load(resp)["info"]["version"]
        return __version__, latest, ""
    except (OSError, ValueError):
        return __version__, None, "could not reach PyPI (offline or blocked?); skill sync still ran"


def _tool_config_path(tool: str, scope: str, repo_path: Path) -> Path:
    """The config file `jsat connect <tool>` writes/reads for a scope."""
    if tool == "claude":
        base = Path.home() / ".claude" if scope == "global" else repo_path / ".claude"
        return base / "settings.json"
    if tool == "bob":
        base = Path.home() / ".bob" if scope == "global" else repo_path / ".bob"
        return base / "settings.json"
    if tool == "opencode":
        from ._cli_connect import _opencode_config_path
        return _opencode_config_path(scope, repo_path)
    if tool == "codex":
        from ._cli_connect import _codex_jsat_config_path
        return _codex_jsat_config_path()
    return Path.home() / ".continue" / "config.json"


def _artifacts_dir(tool: str, scope: str, repo_path: Path) -> Path:
    """Where the installed skill files live for a tool/scope."""
    if tool == "claude":
        base = Path.home() / ".claude" if scope == "global" else repo_path / ".claude"
        return base / "commands"
    if tool == "bob":
        base = Path.home() / ".bob" if scope == "global" else repo_path / ".bob"
        return base / "commands"
    if tool == "codex":
        from ._cli_connect import _codex_jsat_skill_dir
        return _codex_jsat_skill_dir()
    from ._cli_connect import _opencode_commands_dir
    return _opencode_commands_dir(scope, repo_path)


def _is_connected(tool: str, scope: str, repo_path: Path) -> bool:
    """Mirror `jsat connect list`: is a scope actually wired up?"""
    path = _tool_config_path(tool, scope, repo_path)
    if tool == "codex":
        from ._cli_connect import _has_toml_mcp_server
        return _has_toml_mcp_server(path, "jsat")
    if tool == "continue":
        cfg = _read_json(path)
        return any(s.get("name") == "jsat" for s in cfg.get("mcpServers", []))
    key = "mcp" if tool == "opencode" else "mcpServers"
    return bool(_read_json(path).get(key, {}).get("jsat"))


def _expected_artifacts(
    tool: str, scope: str, source: Path, out_root: Path
) -> dict[str, bytes]:
    """Render the exact skill artifacts `jsat connect` would install, into a
    throwaway dir, returning {relative-name: bytes}. Never writes anywhere real."""
    from ._cli_skills_data import (
        _write_bob_commands,
        _write_codex_skill,
        _write_jsat_dispatcher,
    )

    out = out_root / "out"
    out.mkdir(parents=True, exist_ok=True)
    if tool == "claude":
        rendered = _write_jsat_dispatcher(scope, commands_dir=out, source_dir=source)
        return {p.name: p.read_bytes() for p in rendered.glob("jsat*.md")}
    if tool == "opencode":
        rendered = _write_jsat_dispatcher("global", commands_dir=out, source_dir=source)
        return {p.name: p.read_bytes() for p in rendered.glob("jsat*.md")}
    if tool == "codex":
        skill = _write_codex_skill(skill_dir=out, source_dir=source) / "SKILL.md"
        return {"SKILL.md": skill.read_bytes()}
    if tool == "bob":
        rendered = _write_bob_commands(scope, commands_dir=out)
        return {p.name: p.read_bytes() for p in rendered.glob("*.md")}
    raise NotImplementedError(tool)


def _continue_expected_commands() -> list[dict[str, str]]:
    """The customCommands entries `jsat connect continue` would write."""
    from ._cli_skills_data import _JSAT_SKILLS
    return [
        {
            "name": name,
            "description": description,
            "prompt": instruction.replace("$ARGUMENTS", "{input}"),
        }
        for name, (description, instruction) in _JSAT_SKILLS.items()
    ]


def _sync_tool(
    tool: str, scope: str, repo_path: Path, source: Path, check_only: bool
) -> RefreshLine:
    line = RefreshLine(tool=tool, scope=scope, status="ok")
    try:
        if not _is_connected(tool, scope, repo_path):
            line.status = "skipped"
            line.note = "not connected (run `jsat connect %s` first)" % (
                "opencode" if tool == "opencode" else tool
            )
            return line

        if tool == "continue":
            added, modified, removed = _diff_continue(repo_path, check_only)
        else:
            with tempfile.TemporaryDirectory() as td:
                expected = _expected_artifacts(tool, scope, source, Path(td))
                installed_dir = _artifacts_dir(tool, scope, repo_path)
                added, modified, removed = _diff_files(tool, expected, installed_dir)
                if (added or modified or removed) and not check_only:
                    _install_artifacts(tool, scope, repo_path, source)

        line.added, line.modified, line.removed = added, modified, removed
        if added or modified or removed:
            line.status = "would-sync" if check_only else "synced"
            change = f"+{added} added, {modified} modified, {removed} removed"
            line.note = f"would re-sync ({change})" if check_only else f"re-synced ({change})"
        else:
            line.note = "up to date"
        return line
    except Exception as e:  # per-tool degrade, never a crash
        line.status = "error"
        line.note = str(e)
        return line


def _diff_files(tool: str, expected: dict[str, bytes], installed: Path) -> tuple[int, int, int]:
    """Compare expected artifacts to what is on disk. Added / modified / removed."""
    if tool == "codex":
        current = {}
        if (installed / "SKILL.md").exists():
            current["SKILL.md"] = installed / "SKILL.md"
    elif tool == "bob":
        current = {p.name: p for p in installed.glob("*.md")} if installed.exists() else {}
    else:
        # claude / opencode: only jsat-owned files are ever removed or compared.
        current = {p.name: p for p in installed.glob("jsat*.md")} if installed.exists() else {}

    added = [name for name in expected if name not in current]
    removed = [name for name in current if name not in expected]
    shared = set(expected) & set(current)
    modified = [
        name for name in shared if current[name].read_bytes() != expected[name]
    ]
    return len(added), len(modified), len(removed)


def _install_artifacts(tool: str, scope: str, repo_path: Path, source: Path) -> None:
    """Write the skill artifacts for a real scope, exactly like `jsat connect`."""
    from ._cli_skills_data import (
        _write_bob_commands,
        _write_codex_skill,
        _write_jsat_dispatcher,
    )

    installed = _artifacts_dir(tool, scope, repo_path)
    if tool == "claude":
        _write_jsat_dispatcher(scope, commands_dir=installed, source_dir=source)
    elif tool == "opencode":
        _write_jsat_dispatcher("global", commands_dir=installed, source_dir=source)
    elif tool == "codex":
        _write_codex_skill(skill_dir=installed, source_dir=source)
    elif tool == "bob":
        _write_bob_commands(scope, commands_dir=installed)
    else:
        raise NotImplementedError(tool)


def _diff_continue(repo_path: Path, check_only: bool) -> tuple[int, int, int]:
    """Diff `jsat connect continue`'s customCommands against the config, and
    sync when not in check-only mode. User-owned (non-jsat) commands are kept."""
    config_path = Path.home() / ".continue" / "config.json"
    cfg = _read_json(config_path)
    installed = {
        c.get("name"): c
        for c in cfg.get("customCommands", [])
        if str(c.get("name", "")).startswith("jsat-")
    }
    expected = {
        c["name"]: c
        for c in _continue_expected_commands()
    }
    added = [n for n in expected if n not in installed]
    removed = [n for n in installed if n not in expected]
    modified = [
        n for n in set(expected) & set(installed)
        if installed[n] != expected[n]
    ]

    if (added or modified or removed) and not check_only:
        kept = [
            c for c in cfg.get("customCommands", [])
            if not str(c.get("name", "")).startswith("jsat-")
        ]
        cfg["customCommands"] = kept + list(expected.values())
        _write_json(config_path, cfg)
    return len(added), len(modified), len(removed)


def run_refresh(
    *,
    repo: str = ".",
    ai: str | None = None,
    check_only: bool = False,
    do_version: bool = True,
    do_skills: bool = True,
) -> RefreshResult:
    """Check versions and compute/re-apply skill sync for the chosen tools."""
    result = RefreshResult()
    repo_path = Path(repo).resolve()
    if ai and ai not in ("all", *_SKILL_TOOLS):
        raise ValueError(f"unknown AI tool: {ai} (choose from {', '.join((*_SKILL_TOOLS, 'all'))})")

    if do_version:
        installed, latest, note = _pypi_version()
        result.version = installed
        result.version_note = note
        if latest is not None:
            result.update_available = _version_tuple(latest) > _version_tuple(installed)

    if not do_skills:
        return result

    tools = list(_SKILL_TOOLS) if ai is None or ai == "all" else [ai]
    from ._cli_skills_data import _COMMANDS_DIR

    # One throwaway copy of the bundled command files is used FOR ALL tools and
    # scopes, so nothing below can accidentally write into the installed package.
    with tempfile.TemporaryDirectory() as td:
        source = Path(td) / "src"
        shutil.copytree(_COMMANDS_DIR, source)
        for tool in tools:
            scopes = ("project", "global") if tool in _SCOPED_TOOLS else ("global",)
            for scope in scopes:
                result.lines.append(_sync_tool(tool, scope, repo_path, source, check_only))
    return result


def _pip_upgrade(pre: bool) -> tuple[bool, str]:
    """`pip install --upgrade jsat`. Returns (ok, message)."""
    import subprocess
    import sys

    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "jsat"]
    if pre:
        cmd.append("--pre")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except Exception as e:
        return False, str(e)
    if proc.returncode != 0:
        return False, proc.stderr[:300]
    for line in proc.stdout.splitlines():
        if "Successfully installed" in line:
            return True, line
    return True, "already up to date"


@app.command("refresh", rich_help_panel="🔧  Setup & Config")
def cmd_refresh(
    repo: str = typer.Option(".", "--repo", "-r",
                             help="Repo path for project-scope skill targets"),
    ai: str | None = typer.Option(
        None, "--ai",
        help="Only one tool: claude, codex, opencode, bob, continue, or 'all'"),
    check_only: bool = typer.Option(
        False, "--check-only",
        help="Report what would change; write nothing"),
    update: bool = typer.Option(
        False, "--update",
        help="Also `pip install --upgrade jsat` when a newer version is available"),
    pre: bool = typer.Option(
        False, "--pre",
        help="With --update: allow pre-release versions"),
    no_skills: bool = typer.Option(
        False, "--no-skills",
        help="Version check only; skip the skill sync"),
    no_version: bool = typer.Option(
        False, "--no-version",
        help="Skill sync only; skip the PyPI version check"),
) -> None:
    """Refresh JSAT: check for a newer version and re-sync skills.

    Compares the installed version against the latest on PyPI, then re-reads
    the bundled jsat/commands/*.md files and updates every connected AI tool
    that already has JSAT wired — adding new skills, updating modified ones,
    and removing vanished ones. Tools that are not connected are skipped, and
    the installed package itself is never modified.

    \b
    Examples:
      jsat refresh
      jsat refresh --check-only
      jsat refresh --ai codex
      jsat refresh --update
    """
    if ai is not None and ai != "all" and ai not in _SKILL_TOOLS:
        err.print(f"[red]Unknown AI tool:[/] {ai}")
        err.print(f"Choose from: {', '.join((*_SKILL_TOOLS, 'all'))}")
        raise typer.Exit(2)

    result = run_refresh(repo=repo, ai=ai, check_only=check_only,
                         do_version=not no_version, do_skills=not no_skills)

    if not no_version:
        if result.version is None:
            console.print("[bold]Version:[/] skipped")
        elif result.update_available:
            console.print(
                f"[bold]Version:[/] [cyan]{result.version}[/] installed · "
                f"[bold yellow]a newer version is available on PyPI[/] → "
                f"run `jsat update` (or `jsat refresh --update`)")
        elif result.version_note:
            console.print(
                f"[bold]Version:[/] [cyan]{result.version}[/] installed · "
                f"[dim]{result.version_note}[/]")
        else:
            console.print(f"[bold]Version:[/] [cyan]{result.version}[/] installed · up to date")

    if no_skills:
        return

    console.print("\n[bold]Skills:[/]")
    any_connected = False
    for line in result.lines:
        label = _TOOL_LABELS[line.tool]
        scope = f"({line.scope})"
        if line.status == "skipped":
            console.print(f"  [dim]·[/] [bold]{label}[/] {scope} — {line.note}")
        elif line.status == "ok":
            any_connected = True
            console.print(f"  [green]✓[/] [bold]{label}[/] {scope} — {line.note}")
        elif line.status in ("synced", "would-sync"):
            any_connected = True
            icon = "[yellow]→[/]" if line.status == "would-sync" else "[green]✓[/]"
            console.print(f"  {icon} [bold]{label}[/] {scope} — {line.note}")
        else:
            console.print(f"  [red]✗[/] [bold]{label}[/] {scope} — {line.note}")
    if not any_connected:
        console.print("  [dim]No connected skill targets — run `jsat connect <tool>` first.[/]")

    if update and result.update_available and not no_version:
        ok, message = _pip_upgrade(pre)
        if ok:
            console.print(f"[green]✓[/] {message}")
            console.print("[dim]Restart your AI tool — its MCP server holds the old import.[/]")
        else:
            err.print(f"[red]Update failed:[/] {message}")
            raise typer.Exit(1)