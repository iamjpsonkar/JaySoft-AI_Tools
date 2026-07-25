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
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

app = typer.Typer(name="jsat", help="JSAT — Codebase intelligence CLI.",
                  add_completion=True, no_args_is_help=True)
skills_app  = typer.Typer(help="Manage and run JSAT skills.")
connect_app = typer.Typer(help="Connect JSAT to AI tools (Claude, Cursor, etc.).")
app.add_typer(skills_app,  name="skills")
app.add_typer(connect_app, name="connect")

# ── disconnect ─────────────────────────────────────────────────────────────────

@app.command("disconnect")
def cmd_disconnect(
    tool: str = typer.Argument(
        "claude",
        help="AI tool to disconnect from: claude | cursor | all",
    ),
    scope: str = typer.Option(
        "project",
        "--scope", "-s",
        help="'project' | 'global' | 'all'",
    ),
    keep_skills: bool = typer.Option(
        False, "--keep-skills",
        help="Keep /jsat-* slash command files (default: remove them too)",
    ),
) -> None:
    """Remove JSAT from an AI tool — undo jsat connect.

    \b
    jsat disconnect claude                 ← project-level
    jsat disconnect claude --scope global  ← global
    jsat disconnect claude --scope all     ← everywhere
    jsat disconnect cursor                 ← from Cursor
    """
    # Cursor uses a different settings file
    if tool.lower() == "cursor":
        cursor_path = Path.home() / ".cursor" / "mcp.json"
        settings = _read_json(cursor_path)
        if "jsat" in settings.get("mcpServers", {}):
            del settings["mcpServers"]["jsat"]
            _write_json(cursor_path, settings)
            console.print(f"[green]✓[/] Removed JSAT from Cursor: [bold]{cursor_path}[/]")
            console.print("[bold yellow]→ Restart Cursor[/] to apply.\n")
        else:
            console.print("[dim]JSAT not found in Cursor config.[/]")
        return
    scopes = ["project", "global"] if scope == "all" else [scope]
    removed_any = False

    for s in scopes:
        # Determine settings file path
        if s == "global":
            settings_path = Path.home() / ".claude" / "settings.json"
            commands_dir  = Path.home() / ".claude" / "commands"
        else:
            settings_path = Path.cwd() / ".claude" / "settings.json"
            commands_dir  = Path.cwd() / ".claude" / "commands"

        # Remove from mcpServers
        settings = _read_json(settings_path)
        if "jsat" in settings.get("mcpServers", {}):
            del settings["mcpServers"]["jsat"]
            # Remove empty mcpServers key to keep settings clean
            if not settings["mcpServers"]:
                del settings["mcpServers"]
            _write_json(settings_path, settings)
            console.print(f"[green]✓[/] Removed MCP config from [bold]{settings_path}[/]")
            removed_any = True
        else:
            console.print(f"[dim]  JSAT not in {settings_path} — skipping[/]")

        # Remove /jsat-* skill files
        if not keep_skills and commands_dir.exists():
            jsat_skills = list(commands_dir.glob("jsat-*.md"))
            if jsat_skills:
                for skill in jsat_skills:
                    skill.unlink()
                console.print(
                    f"[green]✓[/] Removed {len(jsat_skills)} skill file(s) from "
                    f"[bold]{commands_dir}[/]"
                )
                removed_any = True

    if removed_any:
        console.print("\n[bold yellow]→ Restart Claude Code[/] to apply changes.\n")
    else:
        console.print(
            "[dim]Nothing to disconnect. "
            "Run [bold]jsat connect list[/bold] to see active configs.[/dim]\n"
        )

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
    watch: bool = typer.Option(False, "--watch", "-w", help="Re-index on file changes (needs: brew install entr)"),
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
    if watch:
        import shutil, subprocess
        if not shutil.which("entr"):
            err.print("[yellow]⚠ --watch needs entr:[/] brew install entr")
            raise typer.Exit(1)
        console.print("[dim]Watching for changes... Ctrl+C to stop.[/dim]")
        target = Path(path or ".").resolve()
        jsat_bin = shutil.which("jsat") or "jsat"
        find_cmd = (f'find {target} -name "*.py" -o -name "*.go" -o -name "*.ts" '
                    f'-o -name "*.java" -o -name "*.rb" -o -name "*.rs"')
        subprocess.run(f'{find_cmd} | entr -c {jsat_bin} index {target} --incremental', shell=True)


# ── shell ─────────────────────────────────────────────────────────────────────

@app.command("shell")
def cmd_shell(
    repo: str = typer.Option(".", "--repo", "-r", help="Repository root"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Start the JSAT interactive shell (no AI by default).

    \b
    Use JSAT tools directly:
      index .                    build the graph
      blast-radius src/file.py   trace impact
      security-review            scan for issues
      incident "500 errors"      investigate

    \b
    Launch an AI session from inside the shell:
      switch claude    → Claude Code (full features + JSAT tools)
      switch gpt       → GPT-4o
      switch ollama    → local Ollama

    \b
    Or launch directly from the command line:
      jsat claude      → open Claude with JSAT tools
      jsat gpt         → open GPT with JSAT tools
      jsat ollama      → open Ollama-powered session
    """
    from jsat.tools.shell import launch
    js = _jsat(repo=repo, verbose=verbose)
    launch(js)


def _launch_ai(ai: str, repo: str, verbose: bool) -> None:
    """Shared helper: launch an AI with JSAT MCP tools."""
    from jsat.tools.shell import launch_ai_with_jsat_tools
    js = _jsat(repo=repo, verbose=verbose)
    launch_ai_with_jsat_tools(js, ai=ai)


@app.command("claude")
def cmd_claude(
    repo: str = typer.Option(".", "--repo", "-r", help="Repository root"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Open Claude Code with all JSAT tools available as MCP + /jsat-* skills."""
    _launch_ai("claude", repo, verbose)


@app.command("gpt")
def cmd_gpt(
    repo: str = typer.Option(".", "--repo", "-r"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Open a GPT session with JSAT tools (needs OPENAI_API_KEY)."""
    _launch_ai("gpt", repo, verbose)


@app.command("ollama")
def cmd_ollama(
    repo: str = typer.Option(".", "--repo", "-r"),
    model: str = typer.Option("llama3.2", "--model", "-m", help="Ollama model name"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Open an Ollama session with JSAT tools (local, free, no API key)."""
    from jsat.tools.shell import launch
    js = _jsat(repo=repo, verbose=verbose)
    try:
        js.switch_ai("ollama", model=model)
    except Exception:
        pass
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

    # Services (graph + index)
    svc_t = Table(box=box.ROUNDED, header_style="bold magenta")
    svc_t.add_column("Service")
    svc_t.add_column("Status")
    svc_t.add_column("Detail")
    for svc, info in report.get("services", {}).items():
        svc_t.add_row(svc, _ok(info.get("running")), "")
    g = report.get("graph", {})
    svc_t.add_row("graph", _ok(g.get("ok")),
                  f"backend={g.get('backend','?')}" + (f" err={g['error']}" if g.get("error") else ""))
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
    console.print(Panel(ai_t, title=f"AI Providers  (active: {active_provider}/{ai.get('model','?')})",
                        border_style="blue"))


# ── init ──────────────────────────────────────────────────────────────────────

@app.command("init")
def cmd_init(
    profile: str = typer.Option("solo", "--profile", "-p",
                                help="Profile: solo | team | ci | raspberry-pi"),
    output: str = typer.Option(".jsat/config.yaml", "--output", "-o",
                               help="Config file path (default: .jsat/config.yaml)"),
) -> None:
    """Generate a starter JSAT config inside .jsat/ (keeps your repo root clean)."""
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
    from rich import box
    from rich.table import Table
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


# ── prompt ────────────────────────────────────────────────────────────────────

@app.command("prompt")
def cmd_prompt(
    input_text: str = typer.Argument(..., help="Raw query to optimize"),
    send: bool = typer.Option(False, "--send", "-s", help="Send to AI and return response"),
    ai: Optional[str] = typer.Option(None, "--ai", help="AI override: claude|gpt|ollama"),
    format: Optional[str] = typer.Option(None, "--format", "-f", help="code|plan|json|prose"),
    cot: bool = typer.Option(False, "--cot", help="Enable chain-of-thought"),
    compress: bool = typer.Option(True, "--compress/--no-compress"),
    no_context: bool = typer.Option(False, "--no-context"),
    no_examples: bool = typer.Option(False, "--no-examples"),
    self_critique: bool = typer.Option(False, "--self-critique", help="Run critique pass on response (high-stakes tasks)"),
    diff: bool = typer.Option(False, "--diff", help="Show raw vs optimized"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    max_tokens: int = typer.Option(8192, "--max-tokens"),
    repo: str = typer.Option(".", "--repo", "-r"),
) -> None:
    """Optimize any query into the best possible prompt for your AI.

    \b
    Print optimized prompt:     jsat prompt "improve the retry logic"
    Send to AI:                 jsat prompt --send "improve the retry logic"
    Specific AI + format:       jsat prompt --send --ai claude --format code "write test for refund()"
    Show transformation:        jsat prompt --diff --verbose "refactor webhook handler"
    """
    js = _jsat(repo=repo, verbose=verbose)
    try:
        from jsat.tools.prompt_optimizer import PromptOptimizer
        optimizer = PromptOptimizer(graph=js._get_graph(), cfg=js._cfg, ai=js._get_ai())
    except Exception as e:
        err.print(f"[red]PromptOptimizer error:[/] {e}")
        raise typer.Exit(1) from e

    console.print("[dim]Optimizing...[/dim]", end="\r")
    try:
        result = optimizer.optimize(
            input_text, ai_provider=ai, output_format=format, cot=cot,
            compress=compress, max_context_tokens=max_tokens,
            no_context=no_context, no_examples=no_examples,
        )
    except Exception as e:
        err.print(f"[red]Optimization failed:[/] {e}")
        raise typer.Exit(1) from e

    if verbose:
        t = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
        t.add_column("Agent", style="bold cyan")
        t.add_column("Value")
        t.add_row("Task type", result.task_type)
        t.add_row("Model format", result.model_format)
        t.add_row("Context nodes", str(len(result.context_nodes)))
        t.add_row("Examples used", str(result.examples_used))
        t.add_row("Tokens before", str(result.tokens_before))
        t.add_row("Tokens after", str(result.tokens_after))
        if result.tokens_before:
            saved = max(0, round((result.tokens_before - result.tokens_after) / result.tokens_before * 100))
            t.add_row("Compression", f"{saved}% saved")
        # Show per-agent timings from multi-agent pipeline
        if result.agent_timings:
            t.add_row("", "")
            t.add_row("[dim]Agent timings[/dim]", "[dim](offline, zero LLM)[/dim]")
            for agent, ms in result.agent_timings.items():
                t.add_row(f"  {agent}", f"  {ms}ms")
        console.print(Panel(t, title="Multi-Agent Pipeline", border_style="dim"))

    if diff:
        console.print(Panel(input_text, title="[yellow]Raw input[/]", border_style="yellow"))
        console.print(Panel(result.optimized_prompt, title="[green]Optimized[/]", border_style="green"))

    if result.tokens_before and result.tokens_after:
        saved = max(0, round((result.tokens_before - result.tokens_after) / result.tokens_before * 100))
        console.print(f"[dim]Tokens: {result.tokens_before} → {result.tokens_after} ({saved}% saved) | Task: {result.task_type}[/dim]")

    if not send or dry_run:
        if not diff:
            console.print(Panel(result.optimized_prompt, title="Optimized prompt", border_style="cyan"))
        if dry_run:
            console.print("[dim][dry-run] Not sending.[/dim]")
        return

    # Send to AI
    console.print(f"\n[dim]Sending to {js.active_ai_label()}...[/dim]\n")
    ai_provider = js._get_ai()
    if not ai_provider.is_available():
        err.print(f"[red]AI not reachable:[/] {js.active_ai_label()}")
        raise typer.Exit(1)

    response_text = ""
    try:
        console.print(f"[dim]{js.active_ai_label()}:[/dim] ", end="")
        for chunk in ai_provider.stream(result.optimized_prompt, max_tokens=2048):
            print(chunk, end="", flush=True)
            response_text += chunk
        print()
    except Exception as e:
        err.print(f"[red]AI error:[/] {e}")
        raise typer.Exit(1) from e

    # Self-critique pass (optional, costs 1 extra AI call)
    if self_critique:
        console.print("[dim]Running self-critique pass...[/dim]")
        try:
            corrected = optimizer.self_critique(result.optimized_prompt, response_text, result.task_type)
            if corrected:
                console.print("\n[yellow]⚠ Self-critique found issues — showing corrected version:[/yellow]\n")
                console.print(corrected)
                response_text = corrected
            else:
                console.print("[green]✓ Self-critique: response looks clean[/green]")
        except Exception as e:
            console.print(f"[dim]Self-critique skipped: {e}[/dim]")

    try:
        optimizer.save_to_history(result, response_text)
    except Exception:
        pass


# ── ai ────────────────────────────────────────────────────────────────────────

ai_app = typer.Typer(help="Configure and test the AI provider JSAT uses internally.")
app.add_typer(ai_app, name="ai")


def _detect_available_providers() -> list[dict]:
    """Probe which AI providers are reachable right now."""
    import os
    import shutil
    providers = []

    # Ollama
    ollama_bin = shutil.which("ollama")
    try:
        import httpx
        r = httpx.get("http://localhost:11434/api/tags", timeout=1.0)
        if r.status_code < 400:
            models = [m["name"] for m in r.json().get("models", [])]
            providers.append({
                "name": "ollama", "status": "running",
                "models": models, "free": True,
                "hint": f"ollama serve  (models: {', '.join(models[:3]) or 'none pulled yet'})",
            })
    except Exception:
        if ollama_bin:
            providers.append({"name": "ollama", "status": "installed_not_running",
                               "free": True, "hint": "run: ollama serve"})
        else:
            providers.append({"name": "ollama", "status": "not_installed",
                               "free": True, "hint": "install: brew install ollama"})

    # Anthropic
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    providers.append({
        "name": "anthropic", "status": "key_set" if key else "no_key",
        "free": False, "models": ["claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
        "hint": "set ANTHROPIC_API_KEY" if not key else "ready",
    })

    # OpenAI
    key = os.environ.get("OPENAI_API_KEY", "")
    providers.append({
        "name": "openai", "status": "key_set" if key else "no_key",
        "free": False, "models": ["gpt-4o", "gpt-4o-mini"],
        "hint": "set OPENAI_API_KEY" if not key else "ready",
    })

    # LM Studio / any OpenAI-compat local server
    try:
        import httpx
        r = httpx.get("http://localhost:1234/v1/models", timeout=0.5)
        if r.status_code < 400:
            models = [m["id"] for m in r.json().get("data", [])]
            providers.append({
                "name": "lmstudio", "status": "running", "free": True,
                "models": models, "hint": "LM Studio running at localhost:1234",
            })
    except Exception:
        pass

    return providers


@ai_app.command("status")
def cmd_ai_status() -> None:
    """Show which AI providers JSAT can use and which is currently configured."""
    providers = _detect_available_providers()

    # Current config
    try:
        from jsat._config import load_config
        cfg = load_config()
        current = cfg.ai.provider
        current_model = cfg.ai.model
    except Exception:
        current, current_model = "ollama", "llama3.2"

    table = Table(title="JSAT AI Providers", box=box.ROUNDED, header_style="bold magenta")
    table.add_column("Provider")
    table.add_column("Status")
    table.add_column("Free")
    table.add_column("Notes / Models")

    _status_icons = {
        "running":              "[green]✓ running[/]",
        "key_set":              "[green]✓ key set[/]",
        "installed_not_running":"[yellow]⚠ not running[/]",
        "not_installed":        "[red]✗ not installed[/]",
        "no_key":               "[dim]✗ no key[/]",
    }
    for p in providers:
        name = p["name"]
        is_current = name == current or (name == "lmstudio" and current == "openai_compat")
        label = f"[bold cyan]{name}[/] [dim](active)[/]" if is_current else name
        icon = _status_icons.get(p["status"], p["status"])
        free = "[green]yes[/]" if p.get("free") else "[dim]no[/]"
        notes = p.get("hint", "") or ", ".join(p.get("models", [])[:2])
        table.add_row(label, icon, free, notes)

    console.print(table)
    console.print(
        f"\nCurrently configured: [bold]{current}[/] / [bold]{current_model}[/]\n"
        "Run [bold]jsat ai use <provider>[/] to switch.\n"
    )


@ai_app.command("use")
def cmd_ai_use(
    provider: str = typer.Argument(...,
        help="Provider: ollama | anthropic | openai | lmstudio"),
    model: Optional[str] = typer.Option(None, "--model", "-m",
        help="Model name (auto-selected if omitted)"),
    config_path: str = typer.Option(".jsat/config.yaml", "--config", "-c",
        help="Config file to write (default: .jsat/config.yaml)"),
) -> None:
    """Configure JSAT to use a specific AI provider.

    \b
    Examples:
      jsat ai use ollama                       # local Ollama (free)
      jsat ai use ollama --model llama3.2
      jsat ai use anthropic                    # Claude (needs ANTHROPIC_API_KEY)
      jsat ai use openai --model gpt-4o-mini   # OpenAI (needs OPENAI_API_KEY)
      jsat ai use lmstudio                     # LM Studio at localhost:1234
    """
    import os

    # Defaults per provider
    defaults = {
        "ollama":     {"model": "llama3.2",         "provider_key": "ollama"},
        "anthropic":  {"model": "claude-sonnet-4-6", "provider_key": "anthropic"},
        "openai":     {"model": "gpt-4o-mini",       "provider_key": "openai"},
        "lmstudio":   {"model": "local-model",       "provider_key": "openai_compat",
                       "base_url": "http://localhost:1234/v1"},
    }
    if provider not in defaults:
        err.print(
            f"[red]Unknown provider:[/] {provider!r}\n"
            "Valid: ollama | anthropic | openai | lmstudio"
        )
        raise typer.Exit(1)

    d = defaults[provider]
    chosen_model = model or d["model"]
    chosen_provider = d["provider_key"]
    base_url = d.get("base_url")

    # Pre-flight checks
    if provider == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY"):
        console.print("[yellow]⚠[/] ANTHROPIC_API_KEY is not set.")
        console.print("  Add to your shell: [bold]export ANTHROPIC_API_KEY=sk-ant-...[/]\n")

    if provider == "openai" and not os.environ.get("OPENAI_API_KEY"):
        console.print("[yellow]⚠[/] OPENAI_API_KEY is not set.")
        console.print("  Add to your shell: [bold]export OPENAI_API_KEY=sk-...[/]\n")

    if provider == "ollama":
        try:
            import httpx
            httpx.get("http://localhost:11434/api/tags", timeout=1.0)
        except Exception:
            console.print(
                "[yellow]⚠[/] Ollama is not running.\n"
                "  Start it:  [bold]ollama serve[/]\n"
                "  Pull model: [bold]ollama pull llama3.2[/]\n"
            )

    # Read existing config
    cfg_path = Path(config_path)
    import yaml
    existing: dict = {}
    if cfg_path.exists():
        try:
            existing = yaml.safe_load(cfg_path.read_text()) or {}
        except Exception:
            existing = {}

    # Update ai section
    existing.setdefault("ai", {})
    existing["ai"]["provider"] = chosen_provider
    existing["ai"]["model"] = chosen_model
    if base_url:
        existing["ai"]["base_url"] = base_url

    # Write back
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with cfg_path.open("w") as f:
        yaml.dump(existing, f, default_flow_style=False, sort_keys=False)

    console.print(
        f"\n[green]✓[/] AI provider set: [bold]{chosen_provider}[/] / [bold]{chosen_model}[/]"
    )
    console.print(f"   Written to: [cyan]{cfg_path.resolve()}[/]\n")

    # Quick connectivity test
    console.print("[dim]Testing connection...[/]", end=" ")
    try:
        from jsat._core import JSAT
        js = JSAT(repo=".", log_level="ERROR")
        ai = js._get_ai()
        if ai.is_available():
            console.print("[green]✓ AI is reachable[/]")
            console.print(
                "\nTry it:  [bold]jsat query \"what does this project do?\"[/]\n"
            )
        else:
            console.print("[yellow]⚠ AI not reachable yet[/] (may need key/server)")
    except Exception as e:
        console.print(f"[yellow]⚠ Could not verify:[/] {e}")


@ai_app.command("test")
def cmd_ai_test(
    prompt: str = typer.Argument("Say hello in one sentence.", help="Prompt to send"),
) -> None:
    """Send a test prompt to the configured AI and print the response."""
    js = _jsat()
    console.print(f"[dim]Provider: {js._cfg.ai.provider}/{js._cfg.ai.model}[/]")
    console.print("[dim]Sending prompt...[/]\n")
    try:
        ai = js._get_ai()
        if not ai.is_available():
            err.print(
                "[red]AI is not available.[/] Run [bold]jsat ai status[/] to see options,\n"
                "then [bold]jsat ai use <provider>[/] to configure one."
            )
            raise typer.Exit(1)
        result = ai.complete(prompt, max_tokens=200)
        console.print(f"[green]Response:[/] {result}")
    except Exception as e:
        err.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)


@ai_app.command("models")
def cmd_ai_models() -> None:
    """List available models for the configured AI provider."""
    try:

        import httpx
        js = _jsat()
        provider = js._cfg.ai.provider

        if provider == "ollama":
            r = httpx.get("http://localhost:11434/api/tags", timeout=2.0)
            r.raise_for_status()
            models = [m["name"] for m in r.json().get("models", [])]
            if not models:
                console.print(
                    "[yellow]No models pulled yet.[/]\n"
                    "Pull one: [bold]ollama pull llama3.2[/]   (4 GB, good quality)\n"
                    "          [bold]ollama pull phi3:mini[/]   (2 GB, fast, low RAM)\n"
                    "          [bold]ollama pull qwen2.5-coder:7b[/]  (code-focused)\n"
                )
                return
            console.print(f"\n[bold]Ollama models ({len(models)}):[/]")
            for m in models:
                active = " [cyan]← active[/]" if m == js._cfg.ai.model else ""
                console.print(f"  {m}{active}")

        elif provider == "openai_compat":
            base = js._cfg.ai.base_url or "http://localhost:1234/v1"
            r = httpx.get(f"{base}/models", timeout=2.0)
            r.raise_for_status()
            models = [m["id"] for m in r.json().get("data", [])]
            console.print(f"\n[bold]Models at {base} ({len(models)}):[/]")
            for m in models:
                console.print(f"  {m}")

        else:
            console.print(
                f"[dim]Provider '{provider}' does not expose a local model list.[/]\n"
                f"Current model: [bold]{js._cfg.ai.model}[/]"
            )
    except Exception as e:
        err.print(f"[red]Could not list models:[/] {e}")
        raise typer.Exit(1)


# ── connect ───────────────────────────────────────────────────────────────────

def _jsat_binary() -> str:
    """Return the absolute path of the currently running jsat binary."""
    import shutil
    import sys
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


def _write_jsat_skills(scope: str, commands_dir: Path | None = None) -> Path:
    """Write /jsat-* skill files so Claude Code can call JSAT tools via slash commands."""
    if commands_dir is None:
        if scope == "global":
            commands_dir = Path.home() / ".claude" / "commands"
        else:
            commands_dir = Path.cwd() / ".claude" / "commands"

    commands_dir.mkdir(parents=True, exist_ok=True)

    skills = {
        "jsat-query": (
            "Answer a question about this codebase using JSAT's graph index.",
            'Use the jsat__query MCP tool with question="$ARGUMENTS" to answer '
            "the question using the indexed codebase graph. Show the answer clearly."
        ),
        "jsat-blast-radius": (
            "Trace downstream impact of a file or symbol change.",
            'Use the jsat__blast_radius MCP tool with target="$ARGUMENTS" to trace '
            "impact. Group results by severity: breaking / degraded / warning / safe."
        ),
        "jsat-security": (
            "Run a security scan on the codebase.",
            'Use the jsat__security_review MCP tool with path="$ARGUMENTS" (or "." if empty). '
            "Group findings by severity. Highlight Critical and High issues first."
        ),
        "jsat-incident": (
            "Investigate a production incident using recent git history.",
            'Use the jsat__investigate_incident MCP tool with description="$ARGUMENTS". '
            "Show top hypotheses ranked by score with evidence for each."
        ),
        "jsat-index": (
            "Build or refresh the JSAT codebase graph index.",
            'Use the jsat__index_repo MCP tool with path="$ARGUMENTS" (or "." if empty). '
            "Report how many nodes and edges were indexed."
        ),
        "jsat-status": (
            "Show JSAT index statistics.",
            "Use the jsat__get_index_status MCP tool and display node/edge counts."
        ),
        "jsat-doctor": (
            "Run a JSAT system health check.",
            "Use the jsat__get_jsat_version MCP tool and jsat__get_index_status to "
            "show system status, version, and index health."
        ),
        "jsat-prompt-diff": (
            "Show what the user typed vs what JSAT sent to the AI after optimization.",
            "Use the jsat__prompt_diff MCP tool with query=\"$ARGUMENTS\" to show "
            "the before/after comparison: raw input vs fully optimized prompt with "
            "injected context, constraints, few-shot examples, and model formatting. "
            "Display both sides clearly — label one 'You sent' and the other 'AI received'."
        ),
        "jsat-ithinking": (
            "Apply IThinking meta-cognitive reasoning before acting on a task.",
            "Use the jsat__ithinking_plan MCP tool with task=\"$ARGUMENTS\" to run "
            "IThinking phases 0-4: intent clarification, local feasibility check, "
            "prompt optimisation, task decomposition, and assumption audit. "
            "Display the plan clearly. After the user approves, proceed with the task. "
            "Then use jsat__ithinking_reflect to record what was done."
        ),
        "jsat-think": (
            "Think carefully before acting — IThinking shortcut.",
            "Before doing anything, use the jsat__ithinking_plan MCP tool with "
            "task=\"$ARGUMENTS\" to clarify intent, check assumptions, and decompose "
            "the work. Show the plan and ask for confirmation before proceeding."
        ),
    }

    written = []
    for name, (description, instruction) in skills.items():
        skill_file = commands_dir / f"{name}.md"
        content = f"---\ndescription: {description}\n---\n\n{instruction}\n"
        skill_file.write_text(content, encoding="utf-8")
        written.append(name)

    return commands_dir


@connect_app.command("claude")
def cmd_connect_claude(
    scope: str = typer.Option(
        "project",
        "--scope", "-s",
        help="'project' → .claude/settings.json  |  'global' → ~/.claude/settings.json",
    ),
    repo: str = typer.Option(".", "--repo", "-r",
                              help="Repo path passed to mcp-server (default: current dir)"),
    install_skills: bool = typer.Option(
        True, "--install-skills/--no-skills",
        help="Also install /jsat-* slash commands in Claude Code",
    ),
    show: bool = typer.Option(False, "--show", help="Print the config that was written"),
) -> None:
    """Wire JSAT into Claude Code as an MCP server and install /jsat-* commands.

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

    # Install /jsat-* slash commands
    if install_skills:
        skills_dir = _write_jsat_skills(scope)
        console.print(
            f"[green]✓[/] Installed JSAT slash commands in [bold]{skills_dir}[/]\n"
            "  [cyan]/jsat-query[/]          — ask anything about the codebase\n"
            "  [cyan]/jsat-blast-radius[/]   — trace impact of a change\n"
            "  [cyan]/jsat-security[/]       — security scan\n"
            "  [cyan]/jsat-incident[/]       — investigate an incident\n"
            "  [cyan]/jsat-index[/]          — rebuild the graph\n"
            "  [cyan]/jsat-status[/]         — graph stats\n"
            "  [cyan]/jsat-doctor[/]         — health check\n"
            "  [cyan]/jsat-ithinking[/]      — IThinking: plan before acting\n"
            "  [cyan]/jsat-think[/]          — think carefully before any task\n"
        )

    console.print(
        "[bold yellow]→ Restart Claude Code[/] to activate.\n"
        "  MCP tools: [dim]jsat__query · jsat__blast_radius · jsat__security_review ·[/]\n"
        "             [dim]jsat__investigate_incident · jsat__index_repo · ...[/]\n"
        "  Slash cmds: [dim]/jsat-query · /jsat-blast-radius · /jsat-security · ...[/]\n"
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


# ── ci-setup ──────────────────────────────────────────────────────────────────

@app.command("ci-setup")
def cmd_ci_setup(
    provider: str = typer.Option("github", "--provider", "-p",
                                  help="CI provider: github | gitlab"),
    repo: str = typer.Option(".", "--repo", "-r"),
) -> None:
    """Install JSAT checks into your CI pipeline (blast-radius, security, contract).

    \b
    GitHub Actions:
        jsat ci-setup --provider github

    \b
    GitLab CI:
        jsat ci-setup --provider gitlab
    """
    from pathlib import Path

    repo_path = Path(repo).resolve()

    if provider == "github":
        dest = repo_path / ".github" / "workflows" / "jsat.yml"
        dest.parent.mkdir(parents=True, exist_ok=True)
        content = """\
name: JSAT Analysis

on:
  pull_request:
    branches: [main, develop]

permissions:
  contents: read
  pull-requests: write
  security-events: write

jobs:
  jsat:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install JSAT
        run: pip install "jsat[standard]"

      - name: Index repo (incremental)
        run: jsat index . --incremental

      - name: Blast Radius
        run: |
          jsat blast-radius --diff origin/${{ github.base_ref }}...HEAD \\
            --output blast-radius.md
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}

      - name: API Contract check
        run: jsat contract-check --base origin/${{ github.base_ref }}

      - name: Security Review
        run: jsat security-review . --sarif security.sarif

      - name: Upload SARIF
        uses: github/codeql-action/upload-sarif@v3
        if: always()
        with:
          sarif_file: security.sarif
"""
        dest.write_text(content, encoding="utf-8")
        console.print(f"\n[green]✓[/] Written [bold]{dest}[/]")
        console.print(
            "\nJSAT will now run on every PR:\n"
            "  [cyan]Blast Radius[/] — what does this change break?\n"
            "  [cyan]Contract Check[/] — any breaking API changes?\n"
            "  [cyan]Security[/] — OWASP issues, secrets, CVEs\n\n"
            "Add [bold]ANTHROPIC_API_KEY[/] to GitHub Secrets for AI-powered analysis.\n"
        )

    elif provider == "gitlab":
        dest = repo_path / ".gitlab-ci.yml"
        content = """\
jsat:
  stage: test
  image: python:3.11-slim
  script:
    - pip install "jsat[standard]"
    - jsat index . --incremental
    - jsat blast-radius --diff origin/$CI_DEFAULT_BRANCH...HEAD
    - jsat contract-check --base origin/$CI_DEFAULT_BRANCH
    - jsat security-review . --sarif gl-sast-report.json
  artifacts:
    reports:
      sast: gl-sast-report.json
  only:
    - merge_requests
"""
        # Append to existing file if it exists
        if dest.exists():
            existing = dest.read_text()
            if "jsat:" not in existing:
                dest.write_text(existing.rstrip() + "\n\n" + content, encoding="utf-8")
                console.print(f"[green]✓[/] Appended JSAT job to [bold]{dest}[/]")
            else:
                console.print(f"[dim]JSAT job already in {dest}[/]")
        else:
            dest.write_text(content, encoding="utf-8")
            console.print(f"[green]✓[/] Written [bold]{dest}[/]")
    else:
        err.print(f"[red]Unknown provider:[/] {provider}. Valid: github | gitlab")
        raise typer.Exit(1)


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
    # ── CRITICAL: start serving JSON-RPC IMMEDIATELY.
    # Do NOT call _jsat() here first — that runs detect_system() which pings
    # 4 services (each 0.5s timeout) and potentially auto-indexes the repo.
    # Claude Code has a short timeout for MCP server startup (~5s).
    # Any delay before the first JSON-RPC response causes Claude to mark the
    # server as failed and show "MCP tools not available".
    #
    # Solution: load config lazily inside the MCPServer handlers; start serving
    # before doing any I/O-bound work.

    from pathlib import Path

    repo_path = Path(repo).resolve()

    # Minimal config load — no system detection, no service pings, no indexing
    from jsat._config import load_config
    from jsat._models import JSATConfig

    cfg: JSATConfig = JSATConfig()  # safe defaults
    try:
        cfg = load_config(repo=repo_path)
    except Exception:
        pass  # use defaults if config loading fails

    # Pin paths to repo root
    class _MinimalJSAT:
        """Thin JSAT wrapper for MCP mode — no system detection, no auto-index."""
        def __init__(self) -> None:
            self._repo = repo_path
            self._cfg = cfg
            self._graph = None
            self._ai = None

        def _get_graph(self):
            if self._graph is None:
                # Pin graph path to repo
                graph_path = str(repo_path / ".jsat" / "graph" / "graph.db")
                from jsat._models import GraphConfig
                graph_cfg = GraphConfig(path=graph_path)
                from jsat._graph.sqlite import SQLiteGraph
                self._graph = SQLiteGraph(graph_cfg)
            return self._graph

        def _get_ai(self):
            if self._ai is None:
                import shutil

                from jsat._ai.none import NoOpProvider

                # Auto-detect the best available AI — same priority as auto_configure:
                # claude_cli > anthropic API > openai API > ollama > none
                def _try_claude_cli():
                    if shutil.which("claude"):
                        from jsat._ai.claude_cli import ClaudeCliProvider
                        # Use a clean config with claude model, not whatever
                        # the original config says (e.g. "llama3.2" from Ollama profile)
                        clean_cfg = self._cfg.model_copy(update={
                            "ai": self._cfg.ai.model_copy(update={
                                "provider": "claude_cli",
                                "model": "claude-sonnet-4-6",
                            })
                        })
                        p = ClaudeCliProvider(clean_cfg)
                        if p.is_available():
                            return p
                    return None

                def _try_provider(name: str):
                    try:
                        from jsat._ai import get_ai_provider
                        cfg_copy = self._cfg.model_copy(update={
                            "ai": self._cfg.ai.model_copy(update={"provider": name})
                        })
                        p = get_ai_provider(cfg_copy)
                        if p.is_available():
                            return p
                    except Exception:
                        pass
                    return None

                configured = self._cfg.ai.provider

                # 1. Use configured provider if it actually works
                provider = _try_provider(configured)

                # 2. Fallback chain if configured provider is unreachable
                if provider is None:
                    provider = (
                        _try_claude_cli() or
                        _try_provider("anthropic") or
                        _try_provider("openai") or
                        _try_provider("ollama")
                    )

                self._ai = provider or NoOpProvider()

            return self._ai

        @property
        def index_status(self):
            try:
                g = self._get_graph()
                return {"nodes": g.node_count(), "edges": g.edge_count(),
                        "is_fresh": True}
            except Exception:
                return {"nodes": 0, "edges": 0, "is_fresh": False}

        def index(self, path=None, **kw):
            from jsat.tools.indexer import IndexerTool
            target = Path(path).resolve() if path else repo_path
            return IndexerTool(graph=self._get_graph(), cfg=self._cfg).run(target)

        def query(self, question, **kw):
            from jsat.tools.query import QueryTool
            return QueryTool(graph=self._get_graph(), ai=self._get_ai(),
                             cfg=self._cfg).run(question)

        def blast_radius(self, target, **kw):
            from jsat.tools.blast_radius import BlastRadiusTool
            return BlastRadiusTool(graph=self._get_graph(), cfg=self._cfg).run(target)

        def security_review(self, path=".", **kw):
            from jsat.tools.security import SecurityTool
            return SecurityTool(graph=self._get_graph(), cfg=self._cfg).run(Path(path))

        def investigate_incident(self, description, since="72h", **kw):
            from jsat.tools.incident import IncidentTool
            return IncidentTool(graph=self._get_graph(), ai=self._get_ai(),
                                cfg=self._cfg).run(description, since=since)

        def export(self, output, **kw):
            from jsat.tools.export import ExportTool
            return ExportTool(graph=self._get_graph(), cfg=self._cfg).export(Path(output))

    js = _MinimalJSAT()

    from jsat.mcp.server import MCPServer
    server = MCPServer(js)  # type: ignore[arg-type]
    server.run()  # blocks until stdin closes


# ── clean ────────────────────────────────────────────────────────────────────

@app.command("clean")
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
    root = Path(repo).resolve() / ".jsat"
    targets: list[tuple[str, Path]] = []

    if all_ or cache:   targets.append(("cache",   root / "cache"))
    if all_ or graph:   targets.append(("graph",   root / "graph"))
    if all_ or vectors: targets.append(("vectors", root / "vectors"))
    if all_ or history: targets.append(("history", root / "prompt-history.jsonl"))

    if not targets:
        console.print("[dim]Specify what to clean: --cache | --graph | --vectors | --history | --all[/dim]")
        return

    removed = 0
    for name, p in targets:
        if p.exists():
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink(missing_ok=True)
            console.print(f"[green]✓[/] Removed [bold].jsat/{name}[/]")
            removed += 1
        else:
            console.print(f"[dim]  .jsat/{name} — not found[/dim]")

    if removed:
        console.print(f"\n[bold green]Done.[/] {removed} item(s) removed.")


# ── update ─────────────────────────────────────────────────────────────────────

@app.command("update")
def cmd_update(
    pre: bool = typer.Option(False, "--pre", help="Include pre-release versions"),
) -> None:
    """Upgrade JSAT to the latest version from PyPI."""
    import subprocess, sys
    console.print("[dim]Checking for updates...[/dim]")
    try:
        cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "jsat"]
        if pre:
            cmd.append("--pre")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            # Extract new version from pip output
            for line in result.stdout.splitlines():
                if "Successfully installed" in line:
                    console.print(f"[green]✓[/] {line}")
                    console.print("[dim]Restart your terminal for changes to take effect.[/dim]")
                    return
            console.print(f"[green]✓[/] Already up to date.")
        else:
            err.print(f"[red]Update failed:[/] {result.stderr[:300]}")
            raise typer.Exit(1)
    except Exception as e:
        err.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1) from e


# ── knowledge-ingest ──────────────────────────────────────────────────────────

@app.command("knowledge-ingest")
def cmd_knowledge_ingest(
    path: str = typer.Argument(".", help="Directory or file to ingest"),
    pattern: str = typer.Option("*.md", "--pattern", "-p", help="File glob pattern"),
    category: str = typer.Option("general", "--category", "-c"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be ingested"),
    repo: str = typer.Option(".", "--repo", "-r"),
) -> None:
    """Bulk-ingest markdown files (CLAUDE.md, ADRs, runbooks) into the knowledge base.

    \b
    jsat knowledge-ingest docs/          ingest all .md in docs/
    jsat knowledge-ingest docs/adr/      ingest ADR files
    jsat knowledge-ingest --dry-run .    see what would be ingested
    """
    from jsat.tools.knowledge_ingest import scan_repo, IngestRecord
    target = Path(path).resolve()

    if target.is_file():
        from jsat.tools.knowledge_ingest import ingest_markdown
        records = ingest_markdown(target, category=category)
    else:
        records = scan_repo(target)

    if not records:
        console.print("[dim]No files found to ingest.[/dim]")
        return

    console.print(f"\nFound [bold]{len(records)}[/] entries to ingest from [cyan]{target}[/]\n")
    for r in records[:10]:
        console.print(f"  [dim]{r.category:15}[/] {r.source_file.name}: {r.text[:60]}...")
    if len(records) > 10:
        console.print(f"  [dim]... and {len(records)-10} more[/dim]")

    if dry_run:
        console.print("\n[dim][dry-run] Not ingesting.[/dim]")
        return

    js = _jsat(repo=repo)
    from jsat.tools.knowledge import KnowledgeTool
    tool = KnowledgeTool(graph=js._get_graph(), cfg=js._cfg, ai=js._get_ai())
    ingested = 0
    for r in records:
        try:
            tool.add(r.text, category=r.category)
            ingested += 1
        except Exception as e:
            err.print(f"[yellow]Skip {r.source_file.name}:[/] {e}")

    console.print(f"\n[green]✓[/] Ingested [bold]{ingested}[/] entries into knowledge base.")


# ── remove ────────────────────────────────────────────────────────────────────

@app.command("remove")
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

    cwd = Path.cwd()

    # ── Inventory what will be removed ───────────────────────────────────────
    items: list[tuple[str, Path]] = []

    jsat_dir = cwd / ".jsat"
    for sub in ["graph", "vectors", "cache", "system-profile.json"]:
        p = jsat_dir / sub
        if p.exists():
            items.append((f".jsat/{sub}", p))

    if not keep_config:
        config_yaml = jsat_dir / "config.yaml"
        if config_yaml.exists():
            items.append((".jsat/config.yaml", config_yaml))

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
            console.print(f"[green]✓[/] Removed .jsat/{sub}/")
            removed += 1

    for sub in ["system-profile.json"]:
        p = jsat_dir / sub
        if p.exists():
            p.unlink()
            console.print(f"[green]✓[/] Removed .jsat/{sub}")
            removed += 1

    # Config
    if not keep_config:
        config_yaml = jsat_dir / "config.yaml"
        if config_yaml.exists():
            config_yaml.unlink()
            console.print("[green]✓[/] Removed .jsat/config.yaml")
            removed += 1

    # Remove .jsat/ directory if now empty
    if jsat_dir.exists():
        remaining = list(jsat_dir.iterdir())
        if not remaining:
            jsat_dir.rmdir()
            console.print("[green]✓[/] Removed .jsat/")
        else:
            console.print(
                f"[dim]  .jsat/ kept ({len(remaining)} file(s) remain — "
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
        console.print(f"[green]✓[/] Removed {len(jsat_skills)} JSAT skill file(s) from .claude/commands/")
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


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    app()


if __name__ == "__main__":
    main()
