"""
jsat.cli — Typer CLI entry point.

All commands are thin wrappers around JSAT class or _config helpers.
No tool logic here — pure CLI wiring.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich import box

app = typer.Typer(name="jsat", help="JSAT — Codebase intelligence CLI.",
                  add_completion=True, no_args_is_help=True)
skills_app  = typer.Typer(help="Manage and run JSAT skills.")
connect_app = typer.Typer(help="Connect JSAT to AI tools (Claude, Cursor, etc.).")
app.add_typer(skills_app,  name="skills")
app.add_typer(connect_app, name="connect")

console = Console()
err = Console(stderr=True)


def _jsat(repo: str = ".", verbose: bool = False):
    from jsat._core import JSAT
    from jsat._exceptions import JSATError
    try:
        return JSAT(repo=repo, log_level="DEBUG" if verbose else "WARNING")
    except JSATError as e:
        err.print(f"[bold red]Config error:[/] {e}")
        raise typer.Exit(1) from e


def _ok(v: bool | None) -> str:
    if v is True:  return "[green]✓[/]"
    if v is False: return "[red]✗[/]"
    return "[yellow]~[/]"


# ── version ──────────────────────────────────────────────────────────────────

@app.command("version")
def cmd_version() -> None:
    """Print JSAT version."""
    from jsat import __version__
    console.print(f"jsat {__version__}")


# ── index ─────────────────────────────────────────────────────────────────────

@app.command("index")
def cmd_index(
    path: Optional[str] = typer.Argument(None, help="Directory to index (default: repo root)"),
    branch: str = typer.Option("HEAD", "--branch", "-b"),
    force: bool = typer.Option(False, "--force", "-f", help="Re-index all files"),
    languages: Optional[str] = typer.Option(None, "--languages", "-l",
                                            help="Comma-separated, e.g. python,go"),
    incremental: bool = typer.Option(True, "--incremental/--full"),
) -> None:
    """Index a codebase and build the graph."""
    langs = [l.strip() for l in languages.split(",")] if languages else None
    js = _jsat(repo=path or ".")

    with Progress(SpinnerColumn(), TextColumn("{task.description}"),
                  BarColumn(), TextColumn("{task.percentage:>3.0f}%"),
                  TimeElapsedColumn(), console=console, transient=True) as p:
        task = p.add_task("Indexing…", total=None)
        t0 = time.monotonic()
        try:
            result = js.index(path=path, branch=branch, force=force, languages=langs)
        except Exception as e:
            err.print(f"[bold red]Indexing failed:[/] {e}")
            raise typer.Exit(1) from e
        p.update(task, completed=100, total=100)

    elapsed = time.monotonic() - t0
    console.print(
        f"[green]✓[/] Indexed [bold]{result.nodes_indexed}[/] nodes, "
        f"[bold]{result.edges_indexed}[/] edges in [bold]{elapsed:.1f}s[/]"
    )


# ── shell ─────────────────────────────────────────────────────────────────────

@app.command("shell")
def cmd_shell(
    repo: str = typer.Option(".", "--repo", "-r", help="Repository root"),
) -> None:
    """Start the interactive JSAT REPL."""
    from jsat.tools.shell import launch
    js = _jsat(repo=repo)
    launch(js)


# ── doctor ────────────────────────────────────────────────────────────────────

@app.command("doctor")
def cmd_doctor(
    refresh: bool = typer.Option(False, "--refresh", help="Re-detect system"),
    as_json: bool = typer.Option(False, "--json", help="Output raw JSON"),
) -> None:
    """Run a system health check."""
    js = _jsat()
    try:
        report = js.doctor()
    except Exception as e:
        err.print(f"[bold red]Doctor failed:[/] {e}")
        raise typer.Exit(1) from e

    if as_json:
        console.print_json(json.dumps(report))
        return

    # System
    sys_t = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    sys_t.add_column("Key", style="bold")
    sys_t.add_column("Value")
    s = report.get("system", {})
    sys_t.add_row("Profile", str(report.get("profile", "?")))
    sys_t.add_row("RAM", f"{s.get('ram_gb', '?')} GB")
    sys_t.add_row("Arch", str(s.get("cpu_arch", "?")))
    sys_t.add_row("GPU", str(s.get("gpu", "none")))
    sys_t.add_row("CI mode", str(s.get("is_ci", False)))
    console.print(Panel(sys_t, title="System", border_style="blue"))

    # Services
    svc_t = Table(box=box.ROUNDED, header_style="bold magenta")
    svc_t.add_column("Service")
    svc_t.add_column("Status")
    svc_t.add_column("Detail")
    for svc, info in report.get("services", {}).items():
        svc_t.add_row(svc, _ok(info.get("running")), "")
    g = report.get("graph", {})
    svc_t.add_row("graph", _ok(g.get("ok")),
                  f"backend={g.get('backend','?')}" + (f" err={g['error']}" if g.get("error") else ""))
    ai = report.get("ai", {})
    svc_t.add_row("AI", _ok(ai.get("ok")),
                  f"{ai.get('provider','?')}/{ai.get('model','?')}" + (f" err={ai['error']}" if ai.get("error") else ""))
    idx = report.get("index", {})
    svc_t.add_row("index", _ok(idx.get("is_fresh")),
                  f"nodes={idx.get('nodes',0)} edges={idx.get('edges',0)}")
    console.print(Panel(svc_t, title="Services", border_style="blue"))


# ── init ──────────────────────────────────────────────────────────────────────

@app.command("init")
def cmd_init(
    profile: str = typer.Option("solo", "--profile", "-p",
                                help="Profile: solo | team | ci | raspberry-pi"),
    output: str = typer.Option(".jsat.yaml", "--output", "-o"),
) -> None:
    """Generate a starter .jsat.yaml config."""
    from jsat._config import write_profile_preset
    valid = {"solo", "team", "ci", "raspberry-pi"}
    if profile not in valid:
        err.print(f"[bold red]Unknown profile:[/] {profile!r}. Valid: {', '.join(sorted(valid))}")
        raise typer.Exit(1)
    try:
        write_profile_preset(profile, Path(output))
    except Exception as e:
        err.print(f"[bold red]Init failed:[/] {e}")
        raise typer.Exit(1) from e
    console.print(f"[green]✓[/] Written [bold]{output}[/] for profile [bold]{profile!r}[/]")


# ── export ────────────────────────────────────────────────────────────────────

@app.command("export")
def cmd_export(
    output: str = typer.Argument(..., help="Output path, e.g. backup.jsat.zip"),
    compress: int = typer.Option(6, "--compress", "-z", min=0, max=9),
) -> None:
    """Export the current index to a portable zip."""
    js = _jsat()
    try:
        manifest = js.export(output=output, compress_level=compress)
    except Exception as e:
        err.print(f"[bold red]Export failed:[/] {e}")
        raise typer.Exit(1) from e
    console.print(f"[green]✓[/] Exported to [bold]{output}[/] ({manifest.size_mb:.1f} MB)")


# ── import ────────────────────────────────────────────────────────────────────

@app.command("import")
def cmd_import(
    archive: str = typer.Argument(..., help="Path to .jsat.zip archive"),
    migrate: bool = typer.Option(False, "--migrate"),
) -> None:
    """Restore an index from an exported archive."""
    from jsat._core import JSAT
    try:
        js = JSAT.from_import(archive=archive)
    except Exception as e:
        err.print(f"[bold red]Import failed:[/] {e}")
        raise typer.Exit(1) from e
    s = js.index_status
    console.print(f"[green]✓[/] Restored — nodes={s['nodes']} edges={s['edges']}")


# ── skills ────────────────────────────────────────────────────────────────────

@skills_app.command("list")
def cmd_skills_list() -> None:
    """List installed JSAT skills."""
    from jsat.skills.registry import SkillsRegistry
    js = _jsat()
    registry = SkillsRegistry(js._cfg.skills.dir)
    skills = registry.list_skills()
    if not skills:
        console.print("[dim]No skills installed. Add YAML manifests to skills/[/dim]")
        return
    from rich.table import Table
    from rich import box
    table = Table(box=box.ROUNDED, header_style="bold magenta")
    table.add_column("Name")
    table.add_column("Version")
    table.add_column("Type")
    table.add_column("Description")
    for s in skills:
        table.add_row(s["name"], s.get("version", "?"),
                      s.get("source_type", "?"), s.get("description", ""))
    console.print(table)


@skills_app.command("run")
def cmd_skills_run(
    name: str = typer.Argument(...),
    args: Optional[list[str]] = typer.Option(None, "--args", "-a", help="key=val pairs"),
) -> None:
    """Run a named skill."""
    from jsat.skills.registry import SkillsRegistry
    js = _jsat()
    registry = SkillsRegistry(js._cfg.skills.dir)
    kwargs = {}
    for pair in (args or []):
        if "=" in pair:
            k, _, v = pair.partition("=")
            kwargs[k.strip()] = v.strip()
    try:
        result = registry.run(name, **kwargs)
        console.print(result)
    except Exception as e:
        err.print(f"[bold red]Skill '{name}' failed:[/] {e}")
        raise typer.Exit(1) from e


# ── connect ───────────────────────────────────────────────────────────────────

def _jsat_binary() -> str:
    """Return the absolute path of the currently running jsat binary."""
    import sys, shutil
    # Prefer the script that was invoked
    candidate = Path(sys.argv[0]).resolve()
    if candidate.exists() and candidate.name in ("jsat", "jsat.exe"):
        return str(candidate)
    # Fall back to shutil.which
    found = shutil.which("jsat")
    if found:
        return str(Path(found).resolve())
    # Last resort: derive from sys.executable (same venv)
    bin_dir = Path(sys.executable).parent
    for name in ("jsat", "jsat.exe"):
        p = bin_dir / name
        if p.exists():
            return str(p)
    return "jsat"


def _read_json(path: Path) -> dict:
    """Read JSON file; return {} if missing or invalid."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


@connect_app.command("claude")
def cmd_connect_claude(
    scope: str = typer.Option(
        "project",
        "--scope", "-s",
        help="'project' → .claude/settings.json  |  'global' → ~/.claude/settings.json",
    ),
    repo: str = typer.Option(".", "--repo", "-r",
                              help="Repo path passed to mcp-server (default: current dir)"),
    show: bool = typer.Option(False, "--show", help="Print the config that was written"),
) -> None:
    """Wire JSAT into Claude Code as an MCP server — no manual JSON editing.

    \b
    Project level (just this repo):
        jsat connect claude

    \b
    Global level (all Claude Code sessions):
        jsat connect claude --scope global

    \b
    After running, restart Claude Code. JSAT tools will appear automatically.
    Claude can then call: query, blast_radius, security_review,
    investigate_incident, index_repo, get_index_status, and more.
    """
    binary = _jsat_binary()
    repo_path = str(Path(repo).resolve())

    # Determine settings file location
    if scope == "global":
        settings_path = Path.home() / ".claude" / "settings.json"
        label = "global (~/.claude/settings.json)"
    else:
        settings_path = Path.cwd() / ".claude" / "settings.json"
        label = f"project (.claude/settings.json in {Path.cwd().name}/)"

    # Read existing settings (preserve all other keys)
    settings = _read_json(settings_path)

    # Build the JSAT MCP entry
    jsat_entry = {
        "command": binary,
        "args": ["mcp-server", "--repo", repo_path],
        "env": {},
    }

    # Inject into mcpServers (create key if absent)
    settings.setdefault("mcpServers", {})
    already_present = "jsat" in settings["mcpServers"]
    settings["mcpServers"]["jsat"] = jsat_entry

    _write_json(settings_path, settings)

    action = "Updated" if already_present else "Added"
    console.print(
        f"\n[green]✓[/] {action} JSAT MCP server in [bold]{label}[/]\n"
    )
    console.print(f"  Binary : [cyan]{binary}[/]")
    console.print(f"  Repo   : [cyan]{repo_path}[/]")
    console.print(f"  Config : [cyan]{settings_path}[/]\n")

    if show:
        console.print_json(json.dumps({"mcpServers": {"jsat": jsat_entry}}, indent=2))

    console.print(
        "[bold yellow]→ Restart Claude Code[/] to activate JSAT tools.\n"
        "  Claude will then have access to:\n"
        "  [dim]query · blast_radius · security_review · investigate_incident ·[/]\n"
        "  [dim]index_repo · get_index_status · export_index · get_jsat_version[/]\n"
    )


@connect_app.command("cursor")
def cmd_connect_cursor(
    repo: str = typer.Option(".", "--repo", "-r"),
) -> None:
    """Wire JSAT into Cursor as an MCP server.

    Writes to ~/.cursor/mcp.json (Cursor's MCP config file).
    """
    binary = _jsat_binary()
    repo_path = str(Path(repo).resolve())
    settings_path = Path.home() / ".cursor" / "mcp.json"

    settings = _read_json(settings_path)
    settings.setdefault("mcpServers", {})
    settings["mcpServers"]["jsat"] = {
        "command": binary,
        "args": ["mcp-server", "--repo", repo_path],
    }
    _write_json(settings_path, settings)

    console.print(f"\n[green]✓[/] Added JSAT to Cursor MCP config: [cyan]{settings_path}[/]")
    console.print("[bold yellow]→ Restart Cursor[/] to activate JSAT tools.\n")


@connect_app.command("list")
def cmd_connect_list() -> None:
    """Show all Claude Code and Cursor MCP configs that include JSAT."""
    candidates = [
        Path.home() / ".claude" / "settings.json",
        Path.cwd() / ".claude" / "settings.json",
        Path.home() / ".cursor" / "mcp.json",
    ]
    found_any = False
    for p in candidates:
        data = _read_json(p)
        jsat_cfg = data.get("mcpServers", {}).get("jsat")
        if jsat_cfg:
            found_any = True
            console.print(f"[green]✓[/] [bold]{p}[/]")
            console.print(f"   command: {jsat_cfg.get('command')}")
            console.print(f"   args:    {jsat_cfg.get('args')}\n")
    if not found_any:
        console.print(
            "[dim]No JSAT MCP configs found. Run:[/]\n"
            "  [bold]jsat connect claude[/]           ← project-level\n"
            "  [bold]jsat connect claude --scope global[/]  ← global\n"
        )


@connect_app.command("remove")
def cmd_connect_remove(
    scope: str = typer.Option("project", "--scope", "-s",
                               help="'project' or 'global'"),
) -> None:
    """Remove JSAT from Claude Code's MCP config."""
    if scope == "global":
        settings_path = Path.home() / ".claude" / "settings.json"
    else:
        settings_path = Path.cwd() / ".claude" / "settings.json"

    settings = _read_json(settings_path)
    if "jsat" in settings.get("mcpServers", {}):
        del settings["mcpServers"]["jsat"]
        _write_json(settings_path, settings)
        console.print(f"[green]✓[/] Removed JSAT from [bold]{settings_path}[/]")
    else:
        console.print(f"[dim]JSAT not found in {settings_path}[/]")


# ── mcp-server ───────────────────────────────────────────────────────────────

@app.command("mcp-server")
def cmd_mcp_server(
    repo: str = typer.Option(".", "--repo", "-r", help="Repository root to serve"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """Start the JSAT MCP server (stdin/stdout JSON-RPC 2.0).

    Connect Claude Code or any MCP client by adding to settings.json:

    \b
    {
      "mcpServers": {
        "jsat": {
          "command": "jsat",
          "args": ["mcp-server", "--repo", "/path/to/your/project"]
        }
      }
    }
    """
    import sys
    js = _jsat(repo=repo, verbose=verbose)

    # Build the index if not already done (silent)
    status = js.index_status
    if status.get("nodes", 0) == 0:
        try:
            js.index(path=repo)
        except Exception:
            pass  # MCP server starts even if indexing fails

    from jsat.mcp.server import MCPServer
    server = MCPServer(js)
    # Print capabilities to stderr so Claude Code knows we started
    print(
        '{"jsonrpc":"2.0","id":0,"result":{"protocolVersion":"2024-11-05",'
        '"capabilities":{"tools":{}},"serverInfo":{"name":"jsat","version":"0.1.0"}}}',
        file=sys.stderr,
    )
    server.run()


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    app()


if __name__ == "__main__":
    main()
