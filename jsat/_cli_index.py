"""
jsat._cli_index — Graph & index commands (index, doctor, export, import, clean, remove).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import structlog
import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from ._cli_common import app, console, err, _jsat, _ok, _read_json, _write_json
from ._cli_connect import _CONNECT_LOCATIONS

_log = structlog.get_logger(__name__)

# ── index ─────────────────────────────────────────────────────────────────────

@app.command("index", rich_help_panel="🔍  Graph & Index")
def cmd_index(
    path: str | None = typer.Argument(None, help="Directory to index (default: repo root)"),
    branch: str = typer.Option("HEAD", "--branch", "-b"),
    force: bool = typer.Option(False, "--force", "-f", help="Re-index all files"),
    languages: str | None = typer.Option(None, "--languages", "-l",
                                            help="Comma-separated, e.g. python,go"),
    incremental: bool = typer.Option(True, "--incremental/--full"),
    watch: bool = typer.Option(
        False, "--watch", "-w", help="Re-index on file changes (needs: brew install entr)"
    ),
) -> None:
    """Index a codebase and build the graph."""
    langs = [lang.strip() for lang in languages.split(",")] if languages else None
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
    if watch:
        import shutil
        import subprocess
        if not shutil.which("entr"):
            err.print("[yellow]⚠ --watch needs entr:[/] brew install entr")
            raise typer.Exit(1)
        console.print("[dim]Watching for changes... Ctrl+C to stop.[/dim]")
        target = Path(path or ".").resolve()
        jsat_bin = shutil.which("jsat") or "jsat"
        find_cmd = (f'find {target} -name "*.py" -o -name "*.go" -o -name "*.ts" '
                    f'-o -name "*.java" -o -name "*.rb" -o -name "*.rs"')
        subprocess.run(f'{find_cmd} | entr -c {jsat_bin} index {target} --incremental', shell=True)


# ── doctor ────────────────────────────────────────────────────────────────────

@app.command("doctor", rich_help_panel="🔍  Graph & Index")
def cmd_doctor(
    refresh: bool = typer.Option(False, "--refresh", help="Re-detect system"),
    as_json: bool = typer.Option(False, "--json", help="Output raw JSON"),
) -> None:
    """Run a full system health check.

    Checks: graph backend, AI provider, MCP server, indexed node/edge counts,
    connected tools, and config profile.

    \b
    Examples:
      jsat doctor
      jsat doctor --json
    """
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

    # Services (graph + index)
    svc_t = Table(box=box.ROUNDED, header_style="bold magenta")
    svc_t.add_column("Service")
    svc_t.add_column("Status")
    svc_t.add_column("Detail")
    for svc, info in report.get("services", {}).items():
        svc_t.add_row(svc, _ok(info.get("running")), "")
    g = report.get("graph", {})
    svc_t.add_row(
        "graph", _ok(g.get("ok")),
        f"backend={g.get('backend','?')}" + (f" err={g['error']}" if g.get("error") else ""),
    )
    idx = report.get("index", {})
    svc_t.add_row("index", _ok(idx.get("is_fresh")),
                  f"nodes={idx.get('nodes',0)} edges={idx.get('edges',0)}")
    console.print(Panel(svc_t, title="Services", border_style="blue"))

    # AI providers — show all detected ones
    ai = report.get("ai", {})
    ai_t = Table(box=box.ROUNDED, header_style="bold magenta")
    ai_t.add_column("AI Provider")
    ai_t.add_column("Status")
    ai_t.add_column("Free")
    ai_t.add_column("Switch command")
    active_provider = ai.get("provider", "")
    for p in ai.get("available_providers", []):
        name = p.get("name", "?")
        alias = p.get("alias", "?")
        available = p.get("available", False)
        is_active = p.get("provider_key") == active_provider
        label = f"[bold cyan]{name}[/] [dim](active)[/]" if is_active else name
        status = "[green]✓ available[/]" if available else "[dim]✗ unavailable[/]"
        free = "[green]free[/]" if p.get("free") else "[dim]paid[/]"
        switch_cmd = f"[cyan]switch {alias}[/]" if available else f"[dim]switch {alias}[/]"
        ai_t.add_row(label, status, free, switch_cmd)
    if not ai.get("available_providers"):
        ai_t.add_row("[dim]none detected[/]", "[red]✗[/]", "", "")
    console.print(Panel(
        ai_t,
        title=f"AI Providers  (active: {active_provider}/{ai.get('model','?')})",
        border_style="blue",
    ))

    # Connected AI tools
    tool_t = Table(box=box.ROUNDED, header_style="bold magenta")
    tool_t.add_column("Tool")
    tool_t.add_column("Status")
    tool_t.add_column("Config")
    tool_t.add_column("How to connect")
    for label, cfg_path, key in _CONNECT_LOCATIONS:
        jsat_cfg = _read_json(cfg_path).get(key, {}).get("jsat")
        if jsat_cfg:
            tool_t.add_row(label, "[green]✓ connected[/]", str(cfg_path), "")
        else:
            short = label.split("(")[0].strip().lower().replace(" ", "").replace("code", "")
            cmd_hint = f"jsat connect {short}" if short else ""
            tool_t.add_row(label, "[dim]✗ not wired[/]", "", f"[dim]{cmd_hint}[/]")
    # Continue (array format)
    import json as _json2
    _cont = Path.home() / ".continue" / "config.json"
    try:
        _cont_cfg = _json2.loads(_cont.read_text()) if _cont.exists() else {}
        _jsat_cont = any(s.get("name") == "jsat" for s in _cont_cfg.get("mcpServers", []))
        tool_t.add_row(
            "Continue",
            "[green]✓ connected[/]" if _jsat_cont else "[dim]✗ not wired[/]",
            str(_cont) if _jsat_cont else "",
            "" if _jsat_cont else "[dim]jsat connect continue[/]",
        )
    except Exception:
        pass
    console.print(Panel(tool_t, title="Connected AI Tools", border_style="blue"))

# ── export ────────────────────────────────────────────────────────────────────

@app.command("export", rich_help_panel="🔍  Graph & Index")
def cmd_export(
    output: str = typer.Argument(..., help="Output path, e.g. backup.jsat.zip"),
    compress: int = typer.Option(6, "--compress", "-z", min=0, max=9),
) -> None:
    """Export the current graph index to a portable zip archive.

    Useful for sharing an index with teammates or caching it in CI pipelines.

    \b
    Examples:
      jsat export backup.jsat.zip
      jsat export backup.jsat.zip -z 9   # maximum compression
    """
    js = _jsat()
    try:
        manifest = js.export(output=output, compress_level=compress)
    except Exception as e:
        err.print(f"[bold red]Export failed:[/] {e}")
        raise typer.Exit(1) from e
    console.print(f"[green]✓[/] Exported to [bold]{output}[/] ({manifest.size_mb:.1f} MB)")


# ── import ────────────────────────────────────────────────────────────────────

@app.command("import", rich_help_panel="🔍  Graph & Index")
def cmd_import(
    archive: str = typer.Argument(..., help="Path to .jsat.zip archive"),
    migrate: bool = typer.Option(False, "--migrate"),
) -> None:
    """Restore a graph index from an exported .jsat.zip archive.

    \b
    Examples:
      jsat import backup.jsat.zip
      jsat import backup.jsat.zip --migrate   # allow version mismatch
    """
    from jsat._core import JSAT
    try:
        js = JSAT.from_import(archive=archive)
    except Exception as e:
        err.print(f"[bold red]Import failed:[/] {e}")
        raise typer.Exit(1) from e
    s = js.index_status
    console.print(f"[green]✓[/] Restored — nodes={s['nodes']} edges={s['edges']}")

# ── clean ────────────────────────────────────────────────────────────────────

@app.command("clean", rich_help_panel="🔍  Graph & Index")
def cmd_clean(
    cache: bool = typer.Option(False, "--cache", help="Remove semantic cache only"),
    graph: bool = typer.Option(False, "--graph", help="Remove graph database only"),
    vectors: bool = typer.Option(False, "--vectors", help="Remove vector store only"),
    history: bool = typer.Option(False, "--history", help="Remove prompt history only"),
    all_: bool = typer.Option(False, "--all", "-a", help="Remove all generated files"),
    repo: str = typer.Option(".", "--repo", "-r"),
) -> None:
    """Remove generated JSAT files (cache, graph, vectors, history).

    \b
    jsat clean --cache      remove .jsat/cache/
    jsat clean --graph      remove .jsat/graph/
    jsat clean --vectors    remove .jsat/vectors/
    jsat clean --history    remove .jsat/prompt-history.jsonl
    jsat clean --all        remove all of the above
    """
    import shutil

    from jsat._config import jsat_data_dir
    data_dir = jsat_data_dir(Path(repo).resolve())
    targets: list[tuple[str, Path]] = []

    if all_ or cache:
        targets.append(("cache",   data_dir / "cache"))
    if all_ or graph:
        targets.append(("graph",   data_dir / "graph"))
    if all_ or vectors:
        targets.append(("vectors", data_dir / "vectors"))
    if all_ or history:
        targets.append(("history", data_dir / "prompt-history.jsonl"))

    if not targets:
        console.print(
            "[dim]Specify what to clean: --cache | --graph | --vectors | --history | --all[/dim]"
        )
        return

    removed = 0
    for name, p in targets:
        if p.exists():
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink(missing_ok=True)
            console.print(f"[green]✓[/] Removed [bold]{name}[/] from [dim]{data_dir}[/]")
            removed += 1
        else:
            console.print(f"[dim]  {name} — not found in {data_dir}[/dim]")

    if removed:
        console.print(f"\n[bold green]Done.[/] {removed} item(s) removed.")


# ── remove ────────────────────────────────────────────────────────────────────

@app.command("remove", rich_help_panel="🔍  Graph & Index")
def cmd_remove(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    keep_config: bool = typer.Option(False, "--keep-config",
                                     help="Keep .jsat/config.yaml (preserve settings)"),
) -> None:
    """Remove ALL JSAT artifacts from the current repo.

    \b
    Deletes:
      .jsat/graph/          — codebase graph database
      .jsat/vectors/        — embedding vectors
      .jsat/cache/          — semantic cache
      .jsat/system-profile.json
      .jsat/config.yaml     — (unless --keep-config)
      .jsat/                — directory itself (if empty after cleanup)
      .jsat.yaml            — legacy root config (if present)
      .claude/commands/jsat-*.md  — JSAT slash command skills
      mcpServers.jsat entry in .claude/settings.json

    \b
    Does NOT touch other .claude/ config, your source code, or git history.
    """
    import shutil
    from jsat._config import jsat_data_dir

    cwd = Path.cwd()
    jsat_dir = jsat_data_dir(cwd)

    # ── Inventory what will be removed ───────────────────────────────────────
    items: list[tuple[str, Path]] = []

    for sub in ["graph", "vectors", "cache", "system-profile.json"]:
        p = jsat_dir / sub
        if p.exists():
            items.append((f"{jsat_dir}/{sub}", p))

    if not keep_config:
        config_yaml = jsat_dir / "config.yaml"
        if config_yaml.exists():
            items.append((f"{jsat_dir}/config.yaml", config_yaml))

    legacy = cwd / ".jsat.yaml"
    if legacy.exists():
        items.append((".jsat.yaml (legacy)", legacy))

    # Claude skills
    skills_dir = cwd / ".claude" / "commands"
    jsat_skills = list(skills_dir.glob("jsat-*.md")) if skills_dir.exists() else []
    for skill in jsat_skills:
        items.append((f".claude/commands/{skill.name}", skill))

    # Claude MCP entry
    settings_path = cwd / ".claude" / "settings.json"
    settings = _read_json(settings_path)
    has_mcp = "jsat" in settings.get("mcpServers", {})
    if has_mcp:
        items.append(("mcpServers.jsat in .claude/settings.json", settings_path))

    if not items:
        console.print("[dim]Nothing to remove — JSAT has no artifacts in this directory.[/dim]")
        return

    # ── Show what will be removed ─────────────────────────────────────────────
    console.print(f"\n[bold]JSAT artifacts in[/] [cyan]{cwd}[/cyan]:\n")
    for label, _ in items:
        console.print(f"  [red]✗[/] {label}")

    # ── Confirm ───────────────────────────────────────────────────────────────
    if not yes:
        console.print()
        try:
            confirm = input("Remove all of the above? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            confirm = "n"
        if confirm != "y":
            console.print("[dim]Cancelled.[/dim]")
            return

    console.print()

    # ── Remove ────────────────────────────────────────────────────────────────
    removed = 0

    # Graph, vectors, cache, system-profile (directories + files)
    for sub in ["graph", "vectors", "cache"]:
        p = jsat_dir / sub
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
            console.print(f"[green]✓[/] Removed {sub}/ from [dim]{jsat_dir}[/]")
            removed += 1

    for sub in ["system-profile.json"]:
        p = jsat_dir / sub
        if p.exists():
            p.unlink()
            console.print(f"[green]✓[/] Removed {sub} from [dim]{jsat_dir}[/]")
            removed += 1

    # Config
    if not keep_config:
        config_yaml = jsat_dir / "config.yaml"
        if config_yaml.exists():
            config_yaml.unlink()
            console.print(f"[green]✓[/] Removed config.yaml from [dim]{jsat_dir}[/]")
            removed += 1

    # Remove data directory if now empty
    if jsat_dir.exists():
        remaining = list(jsat_dir.iterdir())
        if not remaining:
            jsat_dir.rmdir()
            console.print(f"[green]✓[/] Removed [dim]{jsat_dir}[/]")
        else:
            console.print(
                f"[dim]  {jsat_dir} kept ({len(remaining)} file(s) remain — "
                f"use --keep-config=false to remove all)[/dim]"
            )

    # Legacy
    if legacy.exists():
        legacy.unlink()
        console.print("[green]✓[/] Removed .jsat.yaml")
        removed += 1

    # Claude skills
    for skill in jsat_skills:
        skill.unlink(missing_ok=True)
    if jsat_skills:
        console.print(
            f"[green]✓[/] Removed {len(jsat_skills)} JSAT skill file(s) from .claude/commands/"
        )
        removed += len(jsat_skills)

    # Claude MCP entry
    if has_mcp:
        del settings["mcpServers"]["jsat"]
        if not settings["mcpServers"]:
            del settings["mcpServers"]
        _write_json(settings_path, settings)
        console.print("[green]✓[/] Removed jsat from .claude/settings.json")
        removed += 1

    console.print(f"\n[bold green]Done.[/] {removed} item(s) removed.")
    if has_mcp:
        console.print("[bold yellow]→ Restart Claude Code[/] to deactivate JSAT tools.\n")
