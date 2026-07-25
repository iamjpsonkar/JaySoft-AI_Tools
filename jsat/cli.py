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
skills_app = typer.Typer(help="Manage and run JSAT skills.")
app.add_typer(skills_app, name="skills")

console = Console()
err = Console(stderr=True)


def _jsat(repo: str = "."):
    from jsat._core import JSAT
    from jsat._exceptions import JSATError
    try:
        return JSAT(repo=repo)
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


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    app()


if __name__ == "__main__":
    main()
