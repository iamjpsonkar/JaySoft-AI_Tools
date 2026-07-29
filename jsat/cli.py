"""
jsat.cli — Typer CLI entry point.

All commands are thin wrappers around JSAT class or _config helpers.
No tool logic here — pure CLI wiring.
"""
from __future__ import annotations

import contextlib
import json
import time
from pathlib import Path

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
        help="Tool to disconnect: claude | codex | cursor | windsurf | continue "
             "| zed | gemini | bob | all",
    ),
    scope: str = typer.Option(
        "project",
        "--scope", "-s",
        help="'project' | 'global' | 'all'  (claude and codex only)",
    ),
    keep_skills: bool = typer.Option(
        False, "--keep-guidance", "--keep-skills",
        help="Keep skill files, instruction blocks, and guidance docs after "
             "disconnecting (--keep-skills is a backward-compatible alias)",
    ),
) -> None:
    """Remove JSAT from an AI tool — undo jsat connect.

    \b
    jsat disconnect claude                  ← Claude Code project-level
    jsat disconnect claude --scope global   ← Claude Code global
    jsat disconnect claude --scope all      ← Claude Code everywhere
    jsat disconnect codex                   ← OpenAI Codex CLI (project)
    jsat disconnect cursor                  ← Cursor
    jsat disconnect windsurf                ← Windsurf
    jsat disconnect continue                ← Continue.dev
    jsat disconnect zed                     ← Zed editor
    jsat disconnect gemini                  ← Gemini CLI
    jsat disconnect all                     ← every tool at once
    """
    import json as _json

    tool_lower = tool.lower()

    # Validate tool name upfront (L7 fix: was previously checked at the end)
    _valid_tools = ("claude", "codex", "cursor", "windsurf", "continue", "zed",
                    "gemini", "bob", "all")
    if tool_lower not in _valid_tools:
        err.print(f"[red]Unknown tool:[/] {tool}. "
                  f"Choose: {' | '.join(_valid_tools)}")
        raise typer.Exit(1)

    removed_any = False

    def _remove_from_standard(label: str, config_path: Path, key: str = "mcpServers") -> bool:
        data = _read_json(config_path)
        if "jsat" in data.get(key, {}):
            del data[key]["jsat"]
            if not data[key]:
                del data[key]
            _write_json(config_path, data)
            console.print(f"[green]✓[/] Removed JSAT from [bold]{label}[/] ({config_path})")
            return True
        return False

    # ── claude ────────────────────────────────────────────────────────────────
    if tool_lower in ("claude", "all"):
        scopes = ["project", "global"] if scope == "all" else [scope]
        if tool_lower == "all":
            scopes = ["project", "global"]
        for s in scopes:
            if s == "global":
                sp = Path.home() / ".claude" / "settings.json"
                cd = Path.home() / ".claude" / "commands"
            else:
                sp = Path.cwd() / ".claude" / "settings.json"
                cd = Path.cwd() / ".claude" / "commands"
            removed_any |= _remove_from_standard("Claude Code", sp)
            if not keep_skills and cd.exists():
                skills = list(cd.glob("jsat-*.md"))
                for f in skills:
                    f.unlink()
                if skills:
                    console.print(
                        f"[green]✓[/] Removed {len(skills)} skill file(s) from [bold]{cd}[/]"
                    )
                    removed_any = True

    # ── codex ─────────────────────────────────────────────────────────────────
    if tool_lower in ("codex", "all"):
        scopes = ["project", "global"] if (scope == "all" or tool_lower == "all") else [scope]
        for s in scopes:
            p = Path.cwd() / ".codex" / "config.json" if s == "project" \
                else Path.home() / ".codex" / "config.json"
            removed_any |= _remove_from_standard("Codex", p)

    # ── cursor ────────────────────────────────────────────────────────────────
    if tool_lower in ("cursor", "all"):
        # Remove from both project and global config on 'all', else just the scope config
        for cp in [Path(Path.cwd() / ".cursor" / "mcp.json"),
                   Path.home() / ".cursor" / "mcp.json"]:
            removed_any |= _remove_from_standard("Cursor", cp)
        if not keep_skills:
            _remove_jsat_block(Path.cwd() / ".cursorrules")

    # ── windsurf ──────────────────────────────────────────────────────────────
    if tool_lower in ("windsurf", "all"):
        removed_any |= _remove_from_standard(
            "Windsurf", Path.home() / ".codeium" / "windsurf" / "mcp_config.json"
        )
        if not keep_skills:
            _remove_jsat_block(Path.cwd() / ".windsurfrules")

    # ── continue ──────────────────────────────────────────────────────────────
    if tool_lower in ("continue", "all"):
        continue_path = Path.home() / ".continue" / "config.json"
        try:
            if continue_path.exists():
                cfg = _json.loads(continue_path.read_text(encoding="utf-8"))
                before_srv = len(cfg.get("mcpServers", []))
                cfg["mcpServers"] = [
                    s for s in cfg.get("mcpServers", []) if s.get("name") != "jsat"
                ]
                if not keep_skills:
                    cfg["customCommands"] = [
                        c for c in cfg.get("customCommands", [])
                        if not c.get("name", "").startswith("jsat-")
                    ]
                if len(cfg["mcpServers"]) < before_srv:
                    continue_path.write_text(_json.dumps(cfg, indent=2), encoding="utf-8")
                    console.print(
                        f"[green]✓[/] Removed JSAT from [bold]Continue.dev[/] ({continue_path})"
                    )
                    removed_any = True
        except Exception as e:
            console.print(f"[dim]Continue: {e}[/]")

    # ── zed ───────────────────────────────────────────────────────────────────
    if tool_lower in ("zed", "all"):
        zed_path = Path.home() / ".config" / "zed" / "settings.json"
        data = _read_json(zed_path)
        if "jsat" in data.get("context_servers", {}):
            del data["context_servers"]["jsat"]
            _write_json(zed_path, data)
            console.print(f"[green]✓[/] Removed JSAT from [bold]Zed[/] ({zed_path})")
            removed_any = True
        if not keep_skills:
            _remove_jsat_block(Path.cwd() / ".zed" / "JSAT.md")

    # ── gemini ────────────────────────────────────────────────────────────────
    if tool_lower in ("gemini", "all"):
        removed_any |= _remove_from_standard(
            "Gemini CLI", Path.home() / ".gemini" / "settings.json"
        )
        if not keep_skills:
            _remove_jsat_block(Path.cwd() / "GEMINI.md")

    # ── bob ───────────────────────────────────────────────────────────────────
    if tool_lower in ("bob", "all"):
        scopes = ["project", "global"] if (scope == "all" or tool_lower == "all") else [scope]
        for s in scopes:
            if s == "global":
                p = Path.home() / ".bob" / "settings.json"
                cd = Path.home() / ".bob" / "commands"
            else:
                p = Path.cwd() / ".bob" / "settings.json"
                cd = Path.cwd() / ".bob" / "commands"
            removed_any |= _remove_from_standard("Bob Shell", p)
            if not keep_skills and cd.exists():
                cmds = list(cd.glob("jsat-*.md"))
                for f in cmds:
                    f.unlink()
                if cmds:
                    console.print(
                        f"[green]✓[/] Removed {len(cmds)} slash command file(s) from [bold]{cd}[/]")
                    removed_any = True
        if not keep_skills:
            _remove_jsat_block(Path.cwd() / "BOB.md")

    if removed_any:
        console.print("\n[bold yellow]→ Restart the AI tool[/] to apply changes.\n")
    else:
        console.print(
            "[dim]Nothing disconnected — JSAT was not found in those configs.[/]\n"
            "Run [bold]jsat connect list[/bold] to see active connections.\n"
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
    if v is True:
        return "[green]✓[/]"
    if v is False:
        return "[red]✗[/]"
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
    Launch a native AI tool from inside the shell:
      switch claude-cli  → Claude Code (full features + JSAT tools)
      switch codex       → OpenAI Codex CLI
      switch gemini      → Google Gemini CLI
      switch cursor      → Cursor IDE
      switch windsurf    → Windsurf IDE
      switch zed         → Zed editor
      switch gpt         → GPT-4o (JSAT shell)
      switch ollama      → local Ollama (JSAT shell)

    \b
    Or launch directly from the command line:
      jsat claude      → Claude Code with JSAT tools
      jsat codex       → Codex CLI with JSAT tools
      jsat cursor      → Cursor IDE with JSAT tools
      jsat windsurf    → Windsurf IDE with JSAT tools
      jsat gemini      → Gemini CLI with JSAT tools
      jsat zed         → Zed with JSAT tools
      jsat gpt         → GPT session (JSAT shell)
      jsat ollama      → Ollama session (JSAT shell)
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
    resume: str | None = typer.Option(None, "--resume", help="Resume a Claude session by ID"),
    continue_: bool = typer.Option(
        False, "--continue", "-c", help="Continue the most recent Claude session"
    ),
) -> None:
    """Open Claude Code with all JSAT tools available as MCP + /jsat-* skills.

    \b
    Fresh session:                jsat claude
    Resume a named session:       jsat claude --resume <session-id>
    Continue most recent session: jsat claude --continue
    """
    from jsat.tools.shell import launch_ai_with_jsat_tools
    js = _jsat(repo=repo, verbose=verbose)
    launch_ai_with_jsat_tools(js, ai="claude", resume=resume, continue_session=continue_)




@app.command("bob")
def cmd_bob(
    repo: str = typer.Option(".", "--repo", "-r", help="Repository root"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    resume: str | None = typer.Option(None, "--resume", help="Resume a Bob session by ID"),
    continue_: bool = typer.Option(
        False, "--continue", "-c", help="Continue the most recent Bob session"
    ),
    mode: str | None = typer.Option(
        None, "--mode", "-m", help="Bob Shell mode: plan, code, advanced, ask"
    ),
) -> None:
    """Open Bob Shell with all JSAT tools available as MCP.

    \b
    Fresh session:                jsat bob
    Resume a named session:       jsat bob --resume <session-id>
    Continue most recent session: jsat bob --continue
    Specific mode:                jsat bob --mode advanced
    """
    from jsat.tools.shell import launch_ai_with_jsat_tools
    js = _jsat(repo=repo, verbose=verbose)
    launch_ai_with_jsat_tools(js, ai="bob", resume=resume, continue_session=continue_, mode=mode)

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
    with contextlib.suppress(Exception):
        js.switch_ai("ollama", model=model)
    launch(js)


# ── AI tool launchers (parity with `jsat claude`) ────────────────────────────

def _tool_install_hint(tool: str) -> str:
    """Return OS-appropriate install instructions for an AI tool."""
    import platform
    system = platform.system()  # "Darwin" | "Linux" | "Windows"
    hints: dict[str, dict[str, str]] = {
        "codex": {
            "Darwin":  "npm install -g @openai/codex",
            "Linux":   "npm install -g @openai/codex",
            "Windows": "npm install -g @openai/codex",
        },
        "cursor": {
            "Darwin":  "brew install --cask cursor  OR  download from cursor.com",
            "Linux":   "download AppImage from cursor.com/download",
            "Windows": "download installer from cursor.com/download",
        },
        "windsurf": {
            "Darwin":  "brew install --cask windsurf  OR  download from windsurf.ai",
            "Linux":   "download AppImage from windsurf.ai/download",
            "Windows": "download installer from windsurf.ai/download",
        },
        "gemini": {
            "Darwin":  "npm install -g @google/gemini-cli  OR  brew install gemini",
            "Linux":   "npm install -g @google/gemini-cli",
            "Windows": "npm install -g @google/gemini-cli",
        },
        "zed": {
            "Darwin":  "brew install --cask zed  OR  download from zed.dev",
            "Linux":   "curl -f https://zed.dev/install.sh | sh",
            "Windows": "not yet available on Windows — check zed.dev",
        },
        "bob": {
            "Darwin":  "npm install -g @ibm/bob-shell",
            "Linux":   "npm install -g @ibm/bob-shell",
            "Windows": "npm install -g @ibm/bob-shell",
        },
    }
    tool_hints = hints.get(tool, {})
    return tool_hints.get(system, tool_hints.get("Darwin", f"install {tool}"))

_TOOL_CONFIG_PATHS: dict[str, tuple[Path, str]] = {
    "codex":    (Path.cwd() / ".codex" / "config.json",          "mcpServers"),
    "cursor":   (Path.home() / ".cursor" / "mcp.json",           "mcpServers"),
    "windsurf": (Path.home() / ".codeium" / "windsurf" / "mcp_config.json", "mcpServers"),
    "gemini":   (Path.home() / ".gemini" / "settings.json",      "mcpServers"),
    "zed":      (Path.home() / ".config" / "zed" / "settings.json", "context_servers"),
    "bob":      (Path.cwd() / ".bob" / "settings.json",          "mcpServers"),
}


def _is_connected(tool: str) -> bool:
    """Return True if JSAT MCP config exists for this tool."""
    entry = _TOOL_CONFIG_PATHS.get(tool)
    if not entry:
        return False
    config_path, key = entry
    return "jsat" in _read_json(config_path).get(key, {})


def _auto_connect(tool: str, repo: str) -> None:
    """Silently connect JSAT to a tool if not already wired."""
    if _is_connected(tool):
        return
    console.print(f"[dim]Auto-connecting JSAT to {tool}...[/dim]")
    binary = _jsat_binary()
    repo_path = str(Path(repo).resolve())
    config_path, key = _TOOL_CONFIG_PATHS[tool]
    if key == "context_servers":
        settings = _read_json(config_path)
        settings.setdefault("context_servers", {})
        settings["context_servers"]["jsat"] = {
            "command": {"path": binary, "args": ["mcp-server", "--repo", repo_path]}
        }
        _write_json(config_path, settings)
    else:
        _connect_mcp_tool(tool.title(), config_path, binary, repo_path, f"Restart {tool.title()}")
    # Also write guidance file
    if tool == "codex":
        _write_instructions_file(config_path.parent / "instructions.md")
    elif tool == "cursor":
        _write_instructions_file(Path(repo).resolve() / ".cursorrules")
    elif tool == "windsurf":
        _write_instructions_file(Path(repo).resolve() / ".windsurfrules")
    elif tool == "gemini":
        _write_instructions_file(Path(repo).resolve() / "GEMINI.md")
    elif tool == "zed":
        _write_instructions_file(Path(repo).resolve() / ".zed" / "JSAT.md")
    console.print(f"[green]✓[/] JSAT connected to [bold]{tool}[/]")


def _launch_tool(
    tool: str,
    binary: str,
    repo: str,
    *,
    gui: bool = False,
    extra_args: list[str] | None = None,
) -> None:
    """Launch a native AI tool binary with JSAT pre-wired."""
    import shutil
    import subprocess

    bin_path = shutil.which(binary or tool)
    if not bin_path:
        err.print(
            f"[red]{tool} not found in PATH.[/]\n"
            f"  Install: [bold]{_tool_install_hint(tool)}[/]"
        )
        raise typer.Exit(1)

    _auto_connect(tool, repo)

    repo_abs = str(Path(repo).resolve())
    cmd = [bin_path] + (extra_args or [])
    if not gui:
        # CLI tools: run in foreground in the repo directory
        console.print(
            f"[green]✓[/] Launching [bold]{tool}[/] with JSAT tools pre-loaded.\n"
            f"[dim]  MCP tools available — JSAT graph at {repo_abs}[/dim]\n"
        )
        subprocess.run(cmd, cwd=repo_abs)
    else:
        # GUI tools: open in background
        cmd_with_dir = cmd + [repo_abs]
        console.print(
            f"[green]✓[/] Opening [bold]{tool}[/] — JSAT tools are pre-loaded.\n"
            f"[dim]  Run `jsat connect {tool}` if tools don't appear.[/dim]\n"
        )
        subprocess.Popen(cmd_with_dir)


@app.command("codex")
def cmd_codex(
    repo: str = typer.Option(".", "--repo", "-r", help="Repository root"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Open Codex CLI with JSAT tools pre-configured.

    \b
    Auto-connects JSAT if not already done, then launches:
      codex        (reads .codex/config.json automatically)

    \b
    JSAT MCP tools are available to Codex immediately.
    Install Codex: npm install -g @openai/codex
    """
    _launch_tool("codex", "codex", repo)


@app.command("cursor")
def cmd_cursor(
    repo: str = typer.Option(".", "--repo", "-r", help="Repository root"),
) -> None:
    """Open Cursor IDE with JSAT tools pre-configured.

    \b
    Auto-connects JSAT if not already done, then opens Cursor
    in the repository directory. JSAT MCP tools are available immediately.
    Install Cursor: brew install --cask cursor
    """
    _launch_tool("cursor", "cursor", repo, gui=True)


@app.command("windsurf")
def cmd_windsurf(
    repo: str = typer.Option(".", "--repo", "-r", help="Repository root"),
) -> None:
    """Open Windsurf IDE with JSAT tools pre-configured.

    \b
    Auto-connects JSAT if not already done, then opens Windsurf
    in the repository directory. JSAT MCP tools are available immediately.
    Install Windsurf: brew install --cask windsurf
    """
    _launch_tool("windsurf", "windsurf", repo, gui=True)


@app.command("gemini")
def cmd_gemini(
    repo: str = typer.Option(".", "--repo", "-r", help="Repository root"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Open Gemini CLI with JSAT tools pre-configured.

    \b
    Auto-connects JSAT if not already done, then launches:
      gemini       (reads ~/.gemini/settings.json + GEMINI.md automatically)

    \b
    Install Gemini CLI: npm install -g @google/gemini-cli
    """
    _launch_tool("gemini", "gemini", repo)


@app.command("zed")
def cmd_zed(
    repo: str = typer.Option(".", "--repo", "-r", help="Repository root"),
) -> None:
    """Open Zed editor with JSAT context server pre-configured.

    \b
    Auto-connects JSAT if not already done, then opens Zed
    in the repository directory.
    Install Zed: brew install --cask zed
    """
    _launch_tool("zed", "zed", repo, gui=True)


# ── crack ─────────────────────────────────────────────────────────────────────

@app.command("crack")
def cmd_crack(
    task: str = typer.Argument(..., help="The complex engineering task to discuss"),
    roles: str | None = typer.Option(
        None, "--roles", "-r",
        help="Comma-separated subset: architect,security,implementer,tester,skeptic",
    ),
    rounds: int = typer.Option(3, "--rounds", "-n", help="Discussion rounds (default 3)"),
    file: str | None = typer.Option(None, "--file", "-f", help="Write output to file"),
    repo: str = typer.Option(".", "--repo"),
) -> None:
    """Run a multi-agent war room on a complex engineering decision.

    \b
    Six specialist agents (architect, security, implementer, tester, skeptic,
    moderator) discuss the task in rounds. Each agent responds to others'
    arguments. The moderator synthesises consensus and an action plan.

    \b
    Examples:
      jsat crack "redesign payment retry system"
      jsat crack --roles architect,security "migrate users table to UUID"
      jsat crack --rounds 2 --file design.md "sync vs async webhooks"
    """
    from jsat.tools.crack import CrackTool
    js = _jsat(repo=repo)
    role_list = [r.strip() for r in roles.split(",")] if roles else None

    with Progress(SpinnerColumn(), TextColumn("{task.description}"),
                  console=console, transient=True) as p:
        p.add_task(f"War room: [bold]{task[:50]}[/]…", total=None)
        result = CrackTool(
            graph=js._get_graph(), cfg=js._cfg, ai=js._get_ai()
        ).run(task, roles=role_list, rounds=rounds, output_file=file,
              repo_path=Path(repo).resolve())

    if not result.ai_available:
        err.print("[yellow]⚠ AI not configured — showing structural placeholders.[/]")
        err.print("[dim]  Run: jsat ai use claude-cli   (or any provider)[/dim]\n")

    # Print discussion summary
    for r in range(1, result.rounds_run + 1):
        console.print(f"\n[bold]Round {r}[/]")
        for s in (st for st in result.statements if st.round_num == r and st.role != "moderator"):
            emoji = {
                "architect": "🏛", "security": "🔒", "implementer": "⚙️",
                "tester": "🧪", "skeptic": "😈",
            }.get(s.role, "•")
            console.print(f"\n  {emoji} [bold]{s.role.upper()}[/]")
            console.print(f"  {s.text[:300]}{'…' if len(s.text)>300 else ''}")

    console.print("\n" + "─" * 60)
    console.print("[bold green]🎯 Final Synthesis[/]\n")
    console.print(result.synthesis or "[dim]No synthesis — AI unavailable.[/dim]")

    if result.output_path:
        console.print(f"\n[dim]Full discussion saved to [cyan]{result.output_path}[/][/dim]")
    console.print(
        f"[dim]{result.rounds_run} rounds · {len(result.roles)} agents · "
        f"{result.elapsed_ms:.0f}ms[/dim]"
    )


# ── short ─────────────────────────────────────────────────────────────────────

@app.command("short")
def cmd_short(
    query: str = typer.Argument(..., help="Question to ask"),
    words: int = typer.Option(50, "--words", "-w", help="Max word count (default 50)"),
    one_line: bool = typer.Option(False, "--one-line", "-1", help="Strict one-sentence answer"),
    repo: str = typer.Option(".", "--repo", "-r"),
) -> None:
    """Ask any question — get the shortest possible correct answer.

    \b
    jsat short "what does process_refund do"
    jsat short --one-line "is PaymentService.process async"
    jsat short --words 20 "explain the retry logic"
    """
    js = _jsat(repo=repo)
    ai = js._get_ai()
    if not ai.is_available():
        err.print(f"[red]AI not reachable:[/] {js.active_ai_label()}")
        raise typer.Exit(1)

    if one_line:
        constraint = "Answer in exactly one sentence. No preamble, no bullet points."
    else:
        constraint = f"Answer in ≤{words} words. Plain language. No preamble or headers."

    full_query = f"{constraint}\n\n{query}"
    console.print(f"[dim]{js.active_ai_label()}:[/dim] ", end="")
    for chunk in ai.stream(full_query, max_tokens=256):
        print(chunk, end="", flush=True)
    print()


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


# ── init ──────────────────────────────────────────────────────────────────────

@app.command("init")
def cmd_init(
    profile: str = typer.Option("solo", "--profile", "-p",
                                help="Profile: solo | team | ci | raspberry-pi"),
    output: str = typer.Option("", "--output", "-o",
                               help="Config file path (default: .jsat/config.yaml, or "
                                    "~/.jsat/config.yaml with --global)"),
    global_: bool = typer.Option(False, "--global", "-g",
                                 help="Write to ~/.jsat/config.yaml — applies to all projects"),
) -> None:
    """Generate a starter JSAT config.

    \b
    Per-repo (default):    jsat init --profile solo
    Global (all projects): jsat init --global --profile solo
    """
    from jsat._config import write_profile_preset
    valid = {"solo", "team", "ci", "raspberry-pi"}
    if profile not in valid:
        err.print(f"[bold red]Unknown profile:[/] {profile!r}. Valid: {', '.join(sorted(valid))}")
        raise typer.Exit(1)

    if global_:
        dest = Path.home() / ".jsat" / "config.yaml"
    elif output:
        dest = Path(output)
    else:
        dest = Path(".jsat") / "config.yaml"

    try:
        write_profile_preset(profile, dest)
    except Exception as e:
        err.print(f"[bold red]Init failed:[/] {e}")
        raise typer.Exit(1) from e
    scope_label = "global (~/.jsat/config.yaml)" if global_ else str(dest)
    console.print(f"[green]✓[/] Written [bold]{scope_label}[/] for profile [bold]{profile!r}[/]")


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
    args: list[str] | None = typer.Option(None, "--args", "-a", help="key=val pairs"),  # noqa: B008
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
    ai: str | None = typer.Option(None, "--ai", help="AI override: claude|gpt|ollama"),
    format: str | None = typer.Option(None, "--format", "-f", help="code|plan|json|prose"),
    cot: bool = typer.Option(False, "--cot", help="Enable chain-of-thought"),
    compress: bool = typer.Option(True, "--compress/--no-compress"),
    no_context: bool = typer.Option(False, "--no-context"),
    no_examples: bool = typer.Option(False, "--no-examples"),
    self_critique: bool = typer.Option(
        False, "--self-critique", help="Run critique pass on response (high-stakes tasks)"
    ),
    rewrite: bool = typer.Option(
        False, "--rewrite", help="Run 1 LLM rewrite agent after offline pipeline"
    ),
    n_agents: int = typer.Option(
        0, "--agents", help="Run N parallel LLM rewrite agents (1-3; omit N for 3)"
    ),
    diff: bool = typer.Option(False, "--diff", help="Show raw vs optimized"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    max_tokens: int = typer.Option(4096, "--max-tokens"),
    repo: str = typer.Option(".", "--repo", "-r"),
) -> None:
    """Optimize any query into the best possible prompt for your AI.

    \b
    Print optimized prompt:       jsat prompt "improve the retry logic"
    Send to AI:                   jsat prompt --send "improve the retry logic"
    LLM rewrite (1 agent):        jsat prompt --rewrite "fix logger in payments"
    Multi-agent rewrite (3):      jsat prompt --agents "fix logger in payments"
    Specific AI + format:         jsat prompt --send --ai claude --format code "test refund()"
    Show transformation:          jsat prompt --diff --verbose "refactor webhook handler"
    """
    # --agents without a value defaults to 3
    if n_agents == 0 and rewrite:
        n_agents = 1
    js = _jsat(repo=repo, verbose=verbose)
    try:
        from jsat.tools.prompt_optimizer import PromptOptimizer
        optimizer = PromptOptimizer(graph=js._get_graph(), cfg=js._cfg, ai=js._get_ai())
    except Exception as e:
        err.print(f"[red]PromptOptimizer error:[/] {e}")
        raise typer.Exit(1) from e

    _rewrite_msg = " (+ LLM rewriting...)" if n_agents > 0 else ""
    console.print(f"[dim]Optimizing{_rewrite_msg}[/dim]", end="\r")
    try:
        result = optimizer.optimize(
            input_text, ai_provider=ai, output_format=format, cot=cot,
            compress=compress, max_context_tokens=max_tokens,
            no_context=no_context, no_examples=no_examples,
            rewrite=rewrite, n_agents=n_agents,
        )
    except Exception as e:
        err.print(f"[red]Optimization failed:[/] {e}")
        raise typer.Exit(1) from e

    if verbose:
        t = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
        t.add_column("Metric", style="bold cyan")
        t.add_column("Value")
        t.add_row("Task type", result.task_type)
        t.add_row("Model format", result.model_format)
        t.add_row("Context nodes", str(len(result.context_nodes)))
        t.add_row("Examples used", str(result.examples_used))
        t.add_row("Tokens before", str(result.tokens_before))
        t.add_row("Tokens after", str(result.tokens_after))
        if result.tokens_before:
            saved = max(
                0,
                round((result.tokens_before - result.tokens_after) / result.tokens_before * 100),
            )
            t.add_row("Compression", f"{saved}% saved")
        if result.rewrite_applied:
            t.add_row("", "")
            t.add_row("[dim]LLM rewriting[/dim]", "[dim](phase 2)[/dim]")
            t.add_row("  Agents run", str(result.rewrite_agents_run))
            t.add_row("  Winner", result.winning_agent or "—")
            t.add_row("  Rewrite time", f"{result.rewrite_elapsed_ms:.0f}ms")
        if result.agent_timings:
            t.add_row("", "")
            t.add_row("[dim]Offline timings[/dim]", "[dim](zero LLM)[/dim]")
            for agent, ms in result.agent_timings.items():
                if not agent.startswith("rewrite_"):
                    t.add_row(f"  {agent}", f"  {ms}ms")
        console.print(Panel(t, title="Prompt Pipeline", border_style="dim"))

    if diff:
        console.print(Panel(input_text, title="[yellow]Raw input[/]", border_style="yellow"))
        console.print(
            Panel(result.optimized_prompt, title="[green]Optimized[/]", border_style="green")
        )

    if getattr(result, "rewrite_skip_reason", None):
        reason = result.rewrite_skip_reason
        if reason == "ai_unavailable":
            err.print(
                "[yellow]⚠ LLM rewrite requested but skipped — "
                "no AI provider configured.[/]"
            )
            err.print("[dim]  Configure one with: jsat ai use <provider>[/dim]")
        else:
            err.print(f"[yellow]⚠ LLM rewrite skipped: {reason}[/]")

    if result.tokens_before and result.tokens_after:
        saved = max(
            0,
            round((result.tokens_before - result.tokens_after) / result.tokens_before * 100),
        )
        rewrite_tag = (
            f" | {result.rewrite_agents_run} agents → {result.winning_agent} won"
            if result.rewrite_applied
            else ""
        )
        console.print(
            f"[dim]Tokens: {result.tokens_before} → {result.tokens_after} ({saved}% saved) "
            f"| Task: {result.task_type}{rewrite_tag}[/dim]"
        )

    if not send or dry_run:
        if not diff:
            console.print(
                Panel(result.optimized_prompt, title="Optimized prompt", border_style="cyan")
            )
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
            corrected = optimizer.self_critique(
                result.optimized_prompt, response_text, result.task_type
            )
            if corrected:
                console.print(
                    "\n[yellow]⚠ Self-critique found issues — "
                    "showing corrected version:[/yellow]\n"
                )
                console.print(corrected)
                response_text = corrected
            else:
                console.print("[green]✓ Self-critique: response looks clean[/green]")
        except Exception as e:
            console.print(f"[dim]Self-critique skipped: {e}[/dim]")

    with contextlib.suppress(Exception):
        optimizer.save_to_history(result, response_text)


# ── tokens ───────────────────────────────────────────────────────────────────

@app.command("tokens")
def cmd_tokens(
    text: str | None = typer.Argument(None, help="Text to analyze (or use --file / pipe stdin)"),
    file: Path | None = typer.Option(None, "--file", "-f", help="Read from file"),  # noqa: B008
    model: str | None = typer.Option(
        None, "--model", "-m",
        help="Model for budget check (e.g. claude-cli, gpt-4o, llama3.2)",
    ),
    compress: bool = typer.Option(False, "--compress", "-c",
                                  help="Compress the text and show savings"),
    strip_comments: bool = typer.Option(False, "--strip-comments",
                                        help="Also strip code comment lines"),
    no_dedup: bool = typer.Option(False, "--no-dedup",
                                  help="Skip semantic deduplication"),
    target: int | None = typer.Option(None, "--target", "-t",
                                         help="Target token ceiling for compression"),
    verbose: bool = typer.Option(False, "--verbose", "-v",
                                 help="Show per-section token breakdown"),
    repo: str = typer.Option(".", "--repo", "-r"),
) -> None:
    """Count tokens, check model budget, and compress text for AI prompts.

    \b
    Count tokens in text:        jsat tokens "explain the payment service"
    Count tokens in file:        jsat tokens --file README.md
    Check budget against model:  jsat tokens --file context.txt --model gpt-4o
    Compress and show diff:      jsat tokens --file context.txt --compress
    Pipe stdin:                  cat myfile.py | jsat tokens --model claude-cli
    """
    import sys

    from jsat.tools.token_optimizer import TokenOptimizer

    # ── Resolve input ─────────────────────────────────────────────────────────
    if file:
        if not file.exists():
            err.print(f"[red]File not found:[/] {file}")
            raise typer.Exit(1)
        content = file.read_text(encoding="utf-8", errors="replace")
        label = str(file)
    elif text:
        content = text
        label = "<argument>"
    elif not sys.stdin.isatty():
        content = sys.stdin.read()
        label = "<stdin>"
    else:
        err.print("[yellow]Provide text as an argument, --file PATH, or pipe via stdin.[/]")
        err.print("[dim]Example: jsat tokens --file README.md --model gpt-4o[/dim]")
        raise typer.Exit(1)

    _jsat(repo=repo)
    opt = TokenOptimizer(graph=None, cfg=None, ai=None)

    if compress:
        report = opt.compress(content, target_tokens=target, model=model,
                              strip_comments=strip_comments, dedup=not no_dedup)
    else:
        report = opt.analyze(content, model=model)

    # ── Build display table ───────────────────────────────────────────────────
    from rich.panel import Panel
    from rich.table import Table

    t = Table(show_header=False, box=None, padding=(0, 1))
    t.add_column(style="dim", min_width=18)
    t.add_column()

    if label not in ("<argument>", "<stdin>"):
        t.add_row("Source", label)

    if compress and report.savings_tokens > 0:
        t.add_row("Tokens before", f"{report.original_tokens:,}")
        color = "green" if report.savings_pct >= 15 else "yellow"
        t.add_row(
            "Tokens after",
            f"[{color}]{report.compressed_tokens:,}[/]  "
            f"[dim](-{report.savings_tokens:,} tokens, {report.savings_pct:.1f}% saved)[/dim]",
        )
        t.add_row("Strategies", ", ".join(report.strategies_applied) or "none")
    elif compress:
        t.add_row(
            "Tokens", f"{report.original_tokens:,}  [dim](already compact — no savings)[/dim]"
        )
    else:
        t.add_row("Tokens", f"{report.original_tokens:,}")

    if report.model:
        t.add_row("Model", report.model)
    if report.model_limit:
        t.add_row("Context limit", f"{report.model_limit:,}")
    if report.budget_used_pct is not None:
        bpct = report.budget_used_pct
        bar_fill = min(20, int(bpct / 5))
        bar = "[green]" + "█" * bar_fill + "[/green]" + "░" * (20 - bar_fill)
        color = "green" if bpct < 50 else ("yellow" if bpct < 85 else "red")
        t.add_row("Budget used", f"{bar}  [{color}]{bpct:.2f}%[/]")
    if report.elapsed_ms:
        t.add_row("Analysis time", f"{report.elapsed_ms:.1f}ms")

    console.print(Panel(t, title="[bold]Token Analysis[/]", border_style="blue"))

    # ── Section breakdown (--verbose) ─────────────────────────────────────────
    if verbose and report.section_breakdown:
        from rich.table import Table as RTable
        sec = RTable("Section", "Tokens", show_header=True, box=None)
        for k, v in sorted(report.section_breakdown.items(), key=lambda x: -x[1]):
            sec.add_row(k, f"{v:,}")
        console.print(sec)

    # ── Compressed output ─────────────────────────────────────────────────────
    if compress and report.savings_tokens > 0:
        console.print()
        console.rule("[dim]Compressed output[/dim]")
        console.print(report.compressed_text)


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
        help="Provider: ollama | anthropic | openai | lmstudio | claude_cli | bob_cli"),
    model: str | None = typer.Option(None, "--model", "-m",
        help="Model name (auto-selected if omitted)"),
    config_path: str = typer.Option("", "--config", "-c",
        help="Config file to write (default: .jsat/config.yaml, or ~/.jsat/config.yaml "
             "with --global)"),
    global_: bool = typer.Option(False, "--global", "-g",
        help="Write to ~/.jsat/config.yaml — applies to all projects"),
) -> None:
    """Configure JSAT to use a specific AI provider.

    \b
    Per-repo (default):    jsat ai use ollama
    Global (all projects): jsat ai use anthropic --global

    \b
    Examples:
      jsat ai use ollama                       # local Ollama (free)
      jsat ai use ollama --model llama3.2
      jsat ai use anthropic                    # Claude (needs ANTHROPIC_API_KEY)
      jsat ai use openai --model gpt-4o-mini   # OpenAI (needs OPENAI_API_KEY)
      jsat ai use lmstudio                     # LM Studio at localhost:1234
      jsat ai use claude_cli --global          # Claude Code CLI, global config
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

    # Resolve config path
    if global_:
        cfg_path = Path.home() / ".jsat" / "config.yaml"
    elif config_path:
        cfg_path = Path(config_path)
    else:
        cfg_path = Path(".jsat") / "config.yaml"

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

    scope_label = "global" if global_ else "project"
    console.print(
        f"\n[green]✓[/] AI provider set: [bold]{chosen_provider}[/] / [bold]{chosen_model}[/]"
        f"  [{scope_label}]"
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
        raise typer.Exit(1) from e


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
        raise typer.Exit(1) from e


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


# ── Shared skill definitions (reused by Claude, Continue, and docs) ────────────

# Each entry: skill-name → (description, instruction)
# $ARGUMENTS is replaced by {input} for Continue's customCommands format.
_JSAT_SKILLS: dict[str, tuple[str, str]] = {
        # ── Graph exploration ─────────────────────────────────────────────────
        "jsat-query": (
            "Answer a question about this codebase using JSAT's graph index.",
            'Use the jsat__query MCP tool with question="$ARGUMENTS" to answer '
            "the question using the indexed codebase graph. Show the answer clearly."
        ),
        "jsat-index": (
            "Build or refresh the JSAT codebase graph index. Supports flags in $ARGUMENTS.",
            """Parse $ARGUMENTS for optional flags, then call jsat__index_repo:

Supported flags (strip from path before passing):
  --force          → pass force=true  (full re-index, ignores incremental cache)
  --languages X,Y  → pass languages=["X","Y"]  (limit to specific languages)
  (no flag)        → incremental index of path (or "." if empty)

Examples:
  /jsat-index .                    → jsat__index_repo(path=".")
  /jsat-index src/ --force         → jsat__index_repo(path="src/", force=true)
  /jsat-index . --languages python,go  → jsat__index_repo(path=".", languages=["python","go"])

After indexing, show: nodes indexed, edges indexed, files parsed vs skipped, parallel workers."""
        ),
        "jsat-status": (
            "Show JSAT index statistics and health.",
            "Use jsat__get_index_status and jsat__get_jsat_version to display node/edge counts, "
            "version, and graph backend."
        ),
        "jsat-doctor": (
            "Run a full JSAT system health check.",
            "Use jsat__health to show system status, AI provider, graph backend, version, "
            "and any configuration issues. Flag anything that needs attention."
        ),
        "jsat-find-function": (
            "Find a function or method in the indexed codebase.",
            'Use jsat__get_function with name="$ARGUMENTS" to locate the function, '
            "show its file, line numbers, parameters, return type, and complexity."
        ),
        "jsat-find-class": (
            "Find a class in the indexed codebase.",
            'Use jsat__get_class with name="$ARGUMENTS" to locate the class, '
            "show its file, base classes, and method count."
        ),
        "jsat-list-services": (
            "List all services found in the indexed codebase.",
            "Use jsat__list_services to show all services with their language and entry point."
        ),
        "jsat-list-endpoints": (
            "List all API endpoints found in the indexed codebase.",
            "Use jsat__list_endpoints to show all HTTP endpoints with method, route, and auth info."
        ),
        "jsat-trace": (
            "Trace a call chain from a symbol through the codebase.",
            'Use jsat__trace_call_chain with symbol="$ARGUMENTS" to show the full call path. '
            "Display as a numbered chain from entrypoint to leaf."
        ),
        # ── Impact & safety ───────────────────────────────────────────────────
        "jsat-blast-radius": (
            "Trace downstream impact of a change. Supports flags in $ARGUMENTS.",
            """Parse $ARGUMENTS for optional flags, then call the right blast-radius tool:

Supported flags:
  --file       → call jsat__blast_radius_file with path=<rest>
  --diff       → call jsat__blast_radius_diff with diff=<rest>
  --symbol     → call jsat__blast_radius_symbol with symbol=<rest>
  (no flag)    → call jsat__blast_radius with target=<rest>

Examples:
  /jsat-blast-radius src/payment/service.py
    → jsat__blast_radius(target="src/payment/service.py")

  /jsat-blast-radius --file src/payment/service.py
    → jsat__blast_radius_file(path="src/payment/service.py")

  /jsat-blast-radius --symbol PaymentService.process
    → jsat__blast_radius_symbol(symbol="PaymentService.process")

Group results by severity: breaking / degraded / warning / safe. Show Mermaid diagram if large."""
        ),
        "jsat-security": (
            "Run a security scan. Supports flags in $ARGUMENTS.",
            """Parse $ARGUMENTS for optional flags, then call the right security tool:

Supported flags:
  --file <path>          → call jsat__security_scan_file with file=<path>
  --secrets              → call jsat__list_secrets to find hardcoded credentials
  --auth                 → call jsat__get_auth_coverage to show auth gaps
  --cves                 → call jsat__get_dependency_cves for CVE check
  --severity critical    → filter to critical only (pass severity_threshold="critical")
  --severity high        → filter to high+ (default: medium)
  (no flag / path only)  → call jsat__security_review with path=<rest or ".">

Examples:
  /jsat-security
    → jsat__security_review(path=".")
  /jsat-security src/payment/
    → jsat__security_review(path="src/payment/")
  /jsat-security --file src/auth/login.py
    → jsat__security_scan_file(file="src/auth/login.py")
  /jsat-security --secrets
    → jsat__list_secrets()
  /jsat-security --severity critical
    → jsat__security_review(path=".", severity_threshold="critical")

Group findings by severity. Highlight Critical and High first. Show file, line, rule, fix."""
        ),
        "jsat-migration": (
            "Validate a database migration file for safety.",
            'Use jsat__validate_migration with path="$ARGUMENTS" to check lock types, '
            "estimate duration, and flag dangerous operations. Suggest zero-downtime alternatives."
        ),
        "jsat-contract": (
            "Check API contract compatibility between branches.",
            'Use jsat__get_api_diff with diff="$ARGUMENTS" to detect breaking changes '
            "in OpenAPI/AsyncAPI specs. Show compatibility score and "
            "breaking vs non-breaking changes."
        ),
        # ── Code quality ──────────────────────────────────────────────────────
        "jsat-review": (
            "Multi-model code review. Supports flags in $ARGUMENTS.",
            """Parse $ARGUMENTS for optional flags, then call the right review tool:

Supported flags:
  --findings        → call jsat__get_review_findings to show results of last review
  --bugs            → call jsat__get_high_confidence_bugs to list confirmed bugs only
  --min high        → filter to high-confidence findings only
  --min medium      → filter to medium+ (default)
  (no flag)         → call jsat__submit_for_review with diff=<rest>

Examples:
  /jsat-review <paste diff here>
    → jsat__submit_for_review(diff="<diff>")

  /jsat-review --findings
    → jsat__get_review_findings()

  /jsat-review --bugs
    → jsat__get_high_confidence_bugs()

Show findings grouped by confidence: high → medium → low. Highlight bugs confirmed by 2+ models."""
        ),
        "jsat-test-gaps": (
            "Find untested code paths and optionally generate tests. Supports flags in $ARGUMENTS.",
            """Parse $ARGUMENTS for optional flags, then call the right test tool:

Supported flags:
  --generate         → after finding gaps, call jsat__generate_unit_test for each
  --integration      → call jsat__generate_integration_test instead
  --contract <A> <B> → call jsat__generate_contract_test between two services
  --untested         → call jsat__list_untested_paths for a flat list
  (no flag)          → call jsat__get_test_gaps with path=<rest or ".">

Examples:
  /jsat-test-gaps src/payment/
    → jsat__get_test_gaps(path="src/payment/")

  /jsat-test-gaps --generate src/payment/
    → jsat__get_test_gaps(path="src/payment/") then generate tests for each gap

  /jsat-test-gaps --untested
    → jsat__list_untested_paths()

  /jsat-test-gaps --contract PaymentService RefundService
    → jsat__generate_contract_test(producer="PaymentService", consumer="RefundService")"""
        ),
        "jsat-coverage": (
            "Show behavioral test coverage estimate for a path.",
            'Use jsat__get_behavioral_coverage with path="$ARGUMENTS" to estimate '
            "how much of the code behavior is covered by tests."
        ),
        # ── Knowledge base ────────────────────────────────────────────────────
        "jsat-knowledge": (
            "Query or manage the JSAT knowledge base. Supports subcommands in $ARGUMENTS.",
            """Parse $ARGUMENTS for an optional subcommand, then call the right tool:

Subcommands:
  add <text>     → call jsat__knowledge_add with text=<text>  (store a new entry)
  list           → call jsat__knowledge_list to show all entries
  list <category>→ call jsat__knowledge_list with category=<category>
  stale <id>     → call jsat__knowledge_flag_stale with entry_id=<id>
  search <text>  → call jsat__knowledge_search with query=<text>
  (no subcommand)→ call jsat__knowledge_query with query=<rest>  (semantic search)

Examples:
  /jsat-knowledge what are the payment service ADRs?
    → jsat__knowledge_query(query="what are the payment service ADRs?")

  /jsat-knowledge add Use tenacity for all retry logic per ADR-007
    → jsat__knowledge_add(text="Use tenacity for all retry logic per ADR-007")

  /jsat-knowledge list
    → jsat__knowledge_list()

  /jsat-knowledge list adr
    → jsat__knowledge_list(category="adr")

  /jsat-knowledge search retry patterns
    → jsat__knowledge_search(query="retry patterns")"""
        ),
        "jsat-knowledge-add": (
            "Add an entry to the JSAT knowledge base.",
            'Use jsat__knowledge_add with text="$ARGUMENTS" to store a new architectural '
            "decision, runbook note, or tribal knowledge entry."
        ),
        "jsat-runbook": (
            "Generate an incident runbook for a service or component.",
            'Use jsat__generate_runbook with target="$ARGUMENTS" to produce a runbook '
            "covering diagnosis steps, rollback procedure, and escalation path."
        ),
        # ── Investigation ─────────────────────────────────────────────────────
        "jsat-incident": (
            "Investigate a production incident. Supports subcommands in $ARGUMENTS.",
            """Parse $ARGUMENTS for an optional subcommand, then call the right tool:

Subcommands:
  hypotheses      → call jsat__get_hypotheses to list ranked root-cause hypotheses
  recent [path]   → call jsat__get_recent_changes to show recent commits in area
  runbook <svc>   → call jsat__generate_runbook to produce an incident runbook
  (no subcommand) → call jsat__investigate_incident with description=<rest>

Examples:
  /jsat-incident 500 errors spiking on checkout since 14:00
    → jsat__investigate_incident(description="500 errors spiking on checkout since 14:00")

  /jsat-incident hypotheses
    → jsat__get_hypotheses()  (after a previous investigation)

  /jsat-incident recent src/payment/
    → jsat__get_recent_changes(target="src/payment/")

  /jsat-incident runbook PaymentService
    → jsat__generate_runbook(target="PaymentService")

Show top hypotheses ranked by score. Include supporting evidence and recent commits."""
        ),
        "jsat-recent": (
            "Show recent changes in the codebase.",
            'Use jsat__get_recent_changes with target="$ARGUMENTS" (or "." if empty) '
            "to list recent commits affecting the area. Highlight risky changes."
        ),
        # ── Prompt & token tools ──────────────────────────────────────────────
        "jsat-prompt": (
            "Optimize a query, THEN answer it with the optimized prompt. Flags pick the optimizer.",
            """This command optimizes the query and then ANSWERS it. Optimization is a
means to a better answer, not the final output.

Step 1 — scan $ARGUMENTS for ALL flags (any order, any combination):

  --rewrite or --agent  → optimize with jsat__prompt_rewrite   (1 LLM rewrite agent)
  --agents              → optimize with jsat__prompt_multi_agent with n_agents=3
  (no optimizer flag)   → optimize with jsat__prompt_optimize  (offline, fastest)
  --diff                → ALSO show jsat__prompt_diff (raw vs optimized) before answering
  --optimize-only       → STOP after optimizing; show the optimized prompt and do NOT answer

Step 2 — the query is every word that is NOT a flag (not starting with --).
Strip all flags; join the remaining words as the query string.

Step 3 — call the selected optimizer with query=<stripped text> to get the
optimized prompt (read it from the tool's "optimized_prompt" field).

Step 4 — UNLESS --optimize-only was given, call jsat__query with
question=<optimized_prompt> and present the ANSWER as the primary result.

Priority when multiple optimizer flags given: --agents beats --rewrite.

Examples:
  /jsat-prompt what is ithinking?
    → jsat__prompt_optimize(query="what is ithinking?")
    → jsat__query(question=<optimized_prompt>)   → show the ANSWER

  /jsat-prompt --rewrite fix logger in ValidateVPAHandler.post
    → jsat__prompt_rewrite(query="fix logger in ValidateVPAHandler.post")
    → jsat__query(question=<optimized_prompt>)   → show the ANSWER

  /jsat-prompt --agents improve the retry logic in PaymentService
    → jsat__prompt_multi_agent(query=..., n_agents=3)
    → jsat__query(question=<optimized_prompt>)   → show the ANSWER

  /jsat-prompt --optimize-only why is checkout failing
    → jsat__prompt_optimize(query="why is checkout failing")
    → show the optimized prompt only; do NOT answer

Output: lead with the ANSWER from jsat__query. Then, briefly, note the optimized
prompt that was used and tokens before→after (plus winning agent for
--rewrite/--agents). For --optimize-only, show ONLY the optimized prompt + token stats."""
        ),
        "jsat-prompt-diff": (
            "Show what you typed vs what JSAT sent to the AI after optimization.",
            'Use jsat__prompt_diff with query="$ARGUMENTS" to show the before/after '
            "comparison: raw input vs fully optimized prompt with injected context, "
            "constraints, few-shot examples, and model formatting. "
            "Label one panel 'You sent' and the other 'AI received'."
        ),
        "jsat-tokens": (
            "Count, compress, or check token budget. Supports flags in $ARGUMENTS.",
            """Parse $ARGUMENTS for optional flags, then call the right token tool:

Supported flags:
  --compress           → call jsat__token_compress with text=<rest>  (apply compression)
  --model <name>       → call jsat__token_budget with text=<rest>, model=<name>
  --budget <model>     → same as --model  (alias)
  (no flag)            → call jsat__token_count with text=<rest>

Examples:
  /jsat-tokens explain the payment service
    → jsat__token_count(text="explain the payment service")

  /jsat-tokens --compress <paste large context here>
    → jsat__token_compress(text="<text>")  → show savings and compressed output

  /jsat-tokens --model gpt-4o <paste context here>
    → jsat__token_budget(text="<text>", model="gpt-4o")  → show % used, headroom, status

  /jsat-tokens --model claude-sonnet-4-6 <paste context>
    → jsat__token_budget(text="<text>", model="claude-sonnet-4-6")

Show: token count, savings (if compressed), budget % used and status (ok/warn/critical)."""
        ),
        "jsat-token-budget": (
            "Check how much of a model's context window a text uses.",
            'Use jsat__token_budget with text="$ARGUMENTS" and model="claude-sonnet-4-6" '
            "(or the model currently in use) to show tokens used, limit, percentage, "
            "headroom, and status (ok / warn / critical)."
        ),
        "jsat-prompt-rewrite": (
            "Rewrite a prompt using offline pipeline + parallel LLM agents for maximum clarity.",
            'Use jsat__prompt_multi_agent with query="$ARGUMENTS" to run 3 specialist LLM agents '
            "(rewrite for clarity, context-expand to fill gaps, constraint-harden for measurable "
            "success criteria) in parallel. Show the winning rewrite with agent name and score. "
            "If the user wants just one agent, use jsat__prompt_rewrite instead."
        ),
        # ── IThinking ─────────────────────────────────────────────────────────
        "jsat-ithinking": (
            "IThinking meta-cognitive reasoning. Supports subcommands in $ARGUMENTS.",
            """Parse $ARGUMENTS for an optional subcommand, then call the right IThinking tool:

Subcommands:
  plan <task>      → call jsat__ithinking_plan with task=<task>  (phases 0-4, default)
  reflect <done>   → call jsat__ithinking_reflect with subtask=<done>  (phase 6 log)
  audit <task>     → call jsat__ithinking_audit_assumptions with task=<task>
  execute <plan>   → call jsat__ithinking_execute with subtask=<plan>
  estimate <task>  → call jsat__ithinking_token_estimate with task=<task>
  (no subcommand)  → call jsat__ithinking_plan with task=<rest>  (same as plan)

Examples:
  /jsat-ithinking refactor the payment retry logic
    → jsat__ithinking_plan(task="refactor the payment retry logic")

  /jsat-ithinking plan add rate limiting to the checkout API
    → jsat__ithinking_plan(task="add rate limiting to the checkout API")

  /jsat-ithinking reflect completed refactor of PaymentService.process()
    → jsat__ithinking_reflect(subtask="completed refactor of PaymentService.process()")

  /jsat-ithinking audit migrate users table to add nullable column
    → jsat__ithinking_audit_assumptions(task="migrate users table to add nullable column")

  /jsat-ithinking estimate write comprehensive tests for the checkout flow
    → jsat__ithinking_token_estimate(task="write comprehensive tests for the checkout flow")

Display plan clearly. After the user approves, proceed. Then reflect on what was done."""
        ),
        "jsat-think": (
            "Think carefully before acting — IThinking shortcut.",
            'Before doing anything, use jsat__ithinking_plan with task="$ARGUMENTS" '
            "to clarify intent, check assumptions, and decompose the work. "
            "Show the plan and ask for confirmation before proceeding."
        ),
        "jsat-reflect": (
            "Record what was done after completing a task (IThinking phase 6).",
            'Use jsat__ithinking_reflect with subtask="$ARGUMENTS" to log the outcome, '
            "what worked, what didn\'t, and any follow-up actions."
        ),
        # ── New features ──────────────────────────────────────────────────────
        "jsat-crack": (
            "Multi-agent war room: architect, security, implementer, tester, "
            "skeptic + moderator discuss a complex task.",
            """Use jsat__crack with task="$ARGUMENTS" to run a multi-agent engineering discussion.

Agents run in rounds, responding to each other's arguments:
  🏛 architect   — system design, patterns, scalability
  🔒 security    — threat model, auth, idempotency
  ⚙  implementer — current code analysis, effort estimation
  🧪 tester      — edge cases, coverage gaps, testability
  😈 skeptic     — devil's advocate, challenges assumptions
  🎯 moderator   — synthesises consensus and action plan

Show each agent's statements by round, then the moderator's final synthesis with:
  ✅ Agreed items
  ⚠️ Disputed items
  ❓ Open questions
  🎯 Recommended action plan""",
        ),
        "jsat-short": (
            "Ask any question — get the briefest possible correct answer (≤3 sentences).",
            'Use jsat__query with question="$ARGUMENTS" but prepend this brevity constraint: '
            '"Answer in ≤3 sentences, plain language. No preamble, no headers, no bullet points." '
            "Show only the AI response — no framing, no metadata.",
        ),
}

# Appended to every generated command so the assistant delivers a real answer
# instead of stopping at raw tool output. Without this, some tools (especially
# ones that return an intermediate artifact like an optimized prompt or a JSON
# blob) get echoed verbatim, which reads as "just showing what the tool does".
_JSAT_CMD_DIRECTIVE = (
    "\n\nHOW TO RESPOND: Actually invoke the tool(s) described above, then reply "
    "with a direct, useful answer built from the result — interpret it for the "
    "user in plain language. Do not merely describe what the tool does, and do "
    "not echo raw JSON. If a tool returns an intermediate artifact (e.g. an "
    "optimized prompt), use it to finish the task rather than presenting it as "
    "the final answer."
)


def _write_jsat_skills(scope: str, commands_dir: Path | None = None) -> Path:
    """Write /jsat-* skill files so Claude Code can call JSAT tools via slash commands."""
    if commands_dir is None:
        if scope == "global":
            commands_dir = Path.home() / ".claude" / "commands"
        else:
            commands_dir = Path.cwd() / ".claude" / "commands"

    commands_dir.mkdir(parents=True, exist_ok=True)

    for name, (description, instruction) in _JSAT_SKILLS.items():
        skill_file = commands_dir / f"{name}.md"
        content = f"---\ndescription: {description}\n---\n\n{instruction}{_JSAT_CMD_DIRECTIVE}\n"
        skill_file.write_text(content, encoding="utf-8")

    return commands_dir


def _write_bob_commands(scope: str, commands_dir: Path | None = None) -> Path:
    """Write /jsat-* slash commands so Bob Shell can call JSAT tools.

    Bob reads markdown commands from .bob/commands/ (project) or ~/.bob/commands/
    (global); the filename becomes the command name. Bob uses shell-style
    argument placeholders, so the $ARGUMENTS used by the Claude skills is
    rewritten to $@ ("all arguments"), and an argument-hint is added when the
    command takes input.
    """
    if commands_dir is None:
        if scope == "global":
            commands_dir = Path.home() / ".bob" / "commands"
        else:
            commands_dir = Path.cwd() / ".bob" / "commands"

    commands_dir.mkdir(parents=True, exist_ok=True)

    def _yaml_dq(s: str) -> str:
        """Double-quote a value for YAML frontmatter. Bob parses frontmatter as
        strict YAML, so descriptions containing ':' etc. must be quoted."""
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'

    for name, (description, instruction) in _JSAT_SKILLS.items():
        body = instruction.replace("$ARGUMENTS", "$@") + _JSAT_CMD_DIRECTIVE
        # Menu descriptions read better with a plain word than the raw token.
        desc = description.replace("$ARGUMENTS", "arguments")
        hint = f"\nargument-hint: {_yaml_dq('<arguments>')}" if "$@" in body else ""
        content = f"---\ndescription: {_yaml_dq(desc)}{hint}\n---\n\n{body}\n"
        (commands_dir / f"{name}.md").write_text(content, encoding="utf-8")

    return commands_dir


@connect_app.command("claude")
def cmd_connect_claude(
    scope: str = typer.Option(
        "project",
        "--scope", "-s",
        help="'project' → .claude/settings.json  |  'global' → ~/.claude/settings.json",
    ),
    global_: bool = typer.Option(
        False, "--global", "-g",
        help="Shorthand for --scope global — installs into ~/.claude/settings.json "
             "and ~/.claude/commands/ for all Claude projects",
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
    Global (all Claude projects, one-time setup):
        jsat connect claude --global

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

    # --global is a shorthand for --scope global
    effective_scope = "global" if global_ else scope

    # Determine settings file location
    if effective_scope == "global":
        settings_path = Path.home() / ".claude" / "settings.json"
        label = "global (~/.claude/settings.json)"
    else:
        settings_path = Path.cwd() / ".claude" / "settings.json"
        label = f"project (.claude/settings.json in {Path.cwd().name}/)"

    # Read existing settings (preserve all other keys)
    settings = _read_json(settings_path)

    # Build the JSAT MCP entry.
    # Inject JSAT_AI_PROVIDER so the MCP subprocess can run LLM-based tools
    # (prompt_rewrite, prompt_multi_agent, etc.) using the claude CLI that is
    # already running in this session — no API key required.
    import shutil as _shutil
    _ai_env: dict[str, str] = {}
    if _shutil.which("claude"):
        _ai_env["JSAT_AI_PROVIDER"] = "claude_cli"
    jsat_entry = {
        "command": binary,
        "args": ["mcp-server", "--repo", repo_path],
        "env": _ai_env,
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
        skills_dir = _write_jsat_skills(effective_scope)
        console.print(
            f"[green]✓[/] Installed {len(_JSAT_SKILLS)} JSAT slash commands "
            f"in [bold]{skills_dir}[/]\n"
            "\n[bold]Graph exploration[/]\n"
            "  [cyan]/jsat-query[/]           — ask anything about the codebase\n"
            "  [cyan]/jsat-find-function[/]   — look up a function by name\n"
            "  [cyan]/jsat-find-class[/]      — look up a class by name\n"
            "  [cyan]/jsat-list-services[/]   — list all indexed services\n"
            "  [cyan]/jsat-list-endpoints[/]  — list all API endpoints\n"
            "  [cyan]/jsat-trace[/]           — trace a call chain\n"
            "  [cyan]/jsat-index[/]           — rebuild the graph (incremental)\n"
            "  [cyan]/jsat-status[/]          — graph stats\n"
            "  [cyan]/jsat-doctor[/]          — system health check\n"
            "\n[bold]Impact & safety[/]\n"
            "  [cyan]/jsat-blast-radius[/]    — trace downstream impact of a change\n"
            "  [cyan]/jsat-security[/]        — OWASP security scan\n"
            "  [cyan]/jsat-migration[/]       — validate DB migration safety\n"
            "  [cyan]/jsat-contract[/]        — API contract compatibility check\n"
            "\n[bold]Code quality[/]\n"
            "  [cyan]/jsat-review[/]          — multi-model parallel code review\n"
            "  [cyan]/jsat-test-gaps[/]       — find untested code, generate tests\n"
            "  [cyan]/jsat-coverage[/]        — behavioral coverage estimate\n"
            "\n[bold]Knowledge & investigation[/]\n"
            "  [cyan]/jsat-knowledge[/]       — query the knowledge base\n"
            "  [cyan]/jsat-knowledge-add[/]   — add to the knowledge base\n"
            "  [cyan]/jsat-runbook[/]         — generate an incident runbook\n"
            "  [cyan]/jsat-incident[/]        — investigate a production incident\n"
            "  [cyan]/jsat-recent[/]          — show recent codebase changes\n"
            "\n[bold]Prompt & token tools[/]\n"
            "  [cyan]/jsat-prompt[/]          — optimize a prompt before sending\n"
            "  [cyan]/jsat-prompt-diff[/]     — see raw vs optimized prompt\n"
            "  [cyan]/jsat-tokens[/]          — count tokens, compress text\n"
            "  [cyan]/jsat-token-budget[/]    — check model context budget\n"
            "\n[bold]IThinking[/]\n"
            "  [cyan]/jsat-ithinking[/]       — full IThinking: plan before acting\n"
            "  [cyan]/jsat-think[/]           — quick: think before any task\n"
            "  [cyan]/jsat-reflect[/]         — record outcome after a task\n"
        )

    console.print(
        "[bold yellow]→ Restart Claude Code[/] to activate.\n"
        "  MCP tools: [dim]jsat__query · jsat__blast_radius · jsat__security_review ·[/]\n"
        "             [dim]jsat__investigate_incident · jsat__index_repo · ...[/]\n"
        "  Slash cmds: [dim]/jsat-query · /jsat-blast-radius · /jsat-security · ...[/]\n"
    )


def _connect_mcp_tool(
    tool_label: str,
    config_path: Path,
    binary: str,
    repo_path: str,
    restart_msg: str,
    env: dict[str, str] | None = None,
) -> None:
    """Write JSAT into a standard {mcpServers: {jsat: {command, args}}} config."""
    settings = _read_json(config_path)
    settings.setdefault("mcpServers", {})
    already = "jsat" in settings["mcpServers"]
    entry: dict = {
        "command": binary,
        "args": ["mcp-server", "--repo", repo_path],
    }
    if env:
        entry["env"] = env
    settings["mcpServers"]["jsat"] = entry
    _write_json(config_path, settings)
    action = "Updated" if already else "Added"
    console.print(f"\n[green]✓[/] {action} JSAT in {tool_label} config: [cyan]{config_path}[/]")
    console.print(f"[bold yellow]→ {restart_msg}[/] to activate JSAT tools.\n")


@connect_app.command("cursor")
def cmd_connect_cursor(
    repo: str = typer.Option(".", "--repo", "-r"),
    scope: str = typer.Option(
        "global", "--scope", "-s",
        help="'project' → .cursor/mcp.json in repo  |  'global' → ~/.cursor/mcp.json",
    ),
    no_instructions: bool = typer.Option(False, "--no-instructions",
                                          help="Skip writing .cursorrules guidance"),
) -> None:
    """Wire JSAT into Cursor as an MCP server + .cursorrules guidance.

    \b
    Project level (just this repo):
        jsat connect cursor --scope project

    \b
    Global level (all Cursor sessions):
        jsat connect cursor            (default: global)
    """
    binary = _jsat_binary()
    repo_path = str(Path(repo).resolve())
    if scope == "project":
        config_path = Path(repo).resolve() / ".cursor" / "mcp.json"
    else:
        config_path = Path.home() / ".cursor" / "mcp.json"
    _connect_mcp_tool("Cursor", config_path, binary, repo_path, "Restart Cursor")
    if not no_instructions:
        rules_path = Path(repo).resolve() / ".cursorrules"
        _write_instructions_file(rules_path)
        _print_instructions_written(
            rules_path, "Cursor",
            "Cursor reads .cursorrules from the project root automatically.",
        )


def _jsat_instructions_block() -> str:
    """Return the standard JSAT tool-guidance block for AI instruction files."""
    return """\
## JSAT — Codebase Intelligence Tools

JSAT is connected as an MCP server. The following tools are available for you to call automatically:

### Graph exploration
- `jsat__query` — answer any codebase question using the indexed graph
- `jsat__get_function` — look up a function by name (returns params, return type, complexity)
- `jsat__get_class` — look up a class (bases, method count, file)
- `jsat__list_services` — list all indexed services
- `jsat__list_endpoints` — list all API endpoints
- `jsat__trace_call_chain` — trace a call chain from a symbol
- `jsat__get_index_status` — graph node/edge counts

### Impact & safety
- `jsat__blast_radius` — trace downstream impact of a change (breaking/degraded/warning/safe)
- `jsat__security_review` — OWASP scan with severity grouping
- `jsat__validate_migration` — DB migration lock type + zero-downtime advice
- `jsat__get_api_diff` — API contract breaking-change detection

### Code quality
- `jsat__submit_for_review` — multi-model parallel code review
- `jsat__get_test_gaps` — find untested code paths
- `jsat__generate_unit_test` — generate a unit test for a function

### Knowledge & investigation
- `jsat__knowledge_query` — search the knowledge base (ADRs, runbooks)
- `jsat__investigate_incident` — root-cause hypotheses ranked by confidence
- `jsat__generate_runbook` — incident runbook for a service

### Prompt & token tools
- `jsat__prompt_optimize` — offline 6-agent prompt pipeline (zero LLM cost)
- `jsat__prompt_multi_agent` — 3 parallel LLM rewrite agents, picks best
- `jsat__token_count` — token count estimation
- `jsat__token_compress` — offline compression (whitespace, dedup, import collapse)
- `jsat__token_budget` — check budget against a model's context window

### When to use JSAT tools
- Before answering "what does X do?" → call `jsat__query` or `jsat__get_function`
- Before editing a file → call `jsat__blast_radius` to understand downstream impact
- Before writing a test → call `jsat__get_test_gaps` to find untested paths
- Before a large refactor → call `jsat__ithinking_plan` for structured planning
- When context is getting long → call `jsat__token_compress` to shrink it
"""


def _write_codex_instructions(scope: str) -> Path:
    """Write/update .codex/instructions.md with JSAT tool guidance."""
    if scope == "global":
        instructions_path = Path.home() / ".codex" / "instructions.md"
    else:
        instructions_path = Path.cwd() / ".codex" / "instructions.md"
    _write_instructions_file(instructions_path)
    return instructions_path


@connect_app.command("codex")
def cmd_connect_codex(
    repo: str = typer.Option(".", "--repo", "-r"),
    scope: str = typer.Option(
        "project", "--scope", "-s",
        help="'project' → .codex/  |  'global' → ~/.codex/",
    ),
    global_: bool = typer.Option(
        False, "--global", "-g",
        help="Shorthand for --scope global — installs into ~/.codex/ for all Codex sessions",
    ),
    no_instructions: bool = typer.Option(
        False, "--no-instructions",
        help="Skip writing instructions.md (MCP config only)",
    ),
) -> None:
    """Wire JSAT into OpenAI Codex CLI as an MCP server + instructions.

    \b
    Project level (just this repo):
        jsat connect codex

    \b
    Global (all Codex sessions, one-time setup):
        jsat connect codex --global

    Writes two files:
      .codex/config.json       — MCP server registration
      .codex/instructions.md   — JSAT tool guidance for the agent
    """
    binary = _jsat_binary()
    repo_path = str(Path(repo).resolve())
    effective_scope = "global" if global_ else scope
    if effective_scope == "global":
        config_path = Path.home() / ".codex" / "config.json"
    else:
        config_path = Path.cwd() / ".codex" / "config.json"
    _connect_mcp_tool("Codex", config_path, binary, repo_path, "Restart Codex")

    if not no_instructions:
        inst_path = _write_codex_instructions(effective_scope)
        console.print(f"[green]✓[/] JSAT tool guidance written to [cyan]{inst_path}[/]")
        console.print(
            "[dim]  Codex reads this file at startup — no restart needed for instructions.[/dim]\n"
        )


def _write_instructions_file(file_path: Path) -> None:
    """Append (or replace) JSAT guidance block in a markdown instruction file."""
    import re as _re2
    marker_start = "<!-- jsat-start -->"
    marker_end = "<!-- jsat-end -->"
    block = f"{marker_start}\n{_jsat_instructions_block()}{marker_end}\n"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    existing = file_path.read_text(encoding="utf-8") if file_path.exists() else ""
    if marker_start in existing:
        updated = _re2.sub(
            rf"{_re2.escape(marker_start)}.*?{_re2.escape(marker_end)}\n?",
            block, existing, flags=_re2.DOTALL,
        )
    else:
        updated = existing.rstrip() + ("\n\n" if existing else "") + block
    file_path.write_text(updated, encoding="utf-8")


def _remove_jsat_block(file_path: Path) -> None:
    """Remove the <!-- jsat-start --> ... <!-- jsat-end --> block from a file."""
    import re as _re2
    if not file_path.exists():
        return
    content = file_path.read_text(encoding="utf-8")
    marker_start = "<!-- jsat-start -->"
    marker_end = "<!-- jsat-end -->"
    if marker_start not in content:
        return
    updated = _re2.sub(
        rf"{_re2.escape(marker_start)}.*?{_re2.escape(marker_end)}\n?",
        "", content, flags=_re2.DOTALL,
    ).strip()
    if updated:
        file_path.write_text(updated + "\n", encoding="utf-8")
    else:
        file_path.unlink()  # file was only JSAT content — remove it entirely


def _print_instructions_written(path: Path, tool: str, note: str = "") -> None:
    console.print(f"[green]✓[/] JSAT tool guidance written to [cyan]{path}[/]")
    if note:
        console.print(f"[dim]  {note}[/dim]\n")


@connect_app.command("windsurf")
def cmd_connect_windsurf(
    repo: str = typer.Option(".", "--repo", "-r"),
    no_instructions: bool = typer.Option(False, "--no-instructions",
                                          help="Skip writing .windsurfrules"),
) -> None:
    """Wire JSAT into Windsurf as an MCP server + .windsurfrules guidance.

    Writes:
      ~/.codeium/windsurf/mcp_config.json  — MCP server registration
      .windsurfrules                         — JSAT tool guidance (project root)
    """
    _connect_mcp_tool(
        "Windsurf",
        Path.home() / ".codeium" / "windsurf" / "mcp_config.json",
        _jsat_binary(), str(Path(repo).resolve()),
        "Restart Windsurf",
    )
    if not no_instructions:
        rules_path = Path(repo).resolve() / ".windsurfrules"
        _write_instructions_file(rules_path)
        _print_instructions_written(
            rules_path, "Windsurf",
            "Windsurf reads .windsurfrules from the project root automatically.",
        )


@connect_app.command("continue")
def cmd_connect_continue(
    repo: str = typer.Option(".", "--repo", "-r"),
    no_instructions: bool = typer.Option(False, "--no-instructions",
                                          help="Skip adding JSAT custom commands"),
) -> None:
    """Wire JSAT into Continue.dev as an MCP server + custom commands.

    Writes to:
      ~/.continue/config.json  — MCP server + customCommands entries
    """
    import json as _json
    binary = _jsat_binary()
    repo_path = str(Path(repo).resolve())
    config_path = Path.home() / ".continue" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        cfg = _json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    except Exception:
        cfg = {}

    # MCP server registration
    servers: list = cfg.get("mcpServers", [])
    servers = [s for s in servers if s.get("name") != "jsat"]
    servers.append({
        "name": "jsat",
        "command": binary,
        "args": ["mcp-server", "--repo", repo_path],
        "type": "stdio",
    })
    cfg["mcpServers"] = servers

    # Custom slash commands — all 28, same as Claude skills (Continue's equivalent)
    if not no_instructions:
        existing_cmds: list = cfg.get("customCommands", [])
        existing_cmds = [c for c in existing_cmds if not c.get("name", "").startswith("jsat-")]
        # Reuse _JSAT_SKILLS — convert $ARGUMENTS → {input} for Continue format
        jsat_commands = [
            {
                "name": name,
                "description": description,
                "prompt": instruction.replace("$ARGUMENTS", "{input}"),
            }
            for name, (description, instruction) in _JSAT_SKILLS.items()
        ]
        cfg["customCommands"] = existing_cmds + jsat_commands

    config_path.write_text(_json.dumps(cfg, indent=2), encoding="utf-8")

    console.print(f"\n[green]✓[/] Added JSAT to Continue config: [cyan]{config_path}[/]")
    if not no_instructions:
        console.print(
            f"[green]✓[/] Added {len(_JSAT_SKILLS)} [cyan]/jsat-*[/] custom commands to Continue"
        )
    console.print(
        "[bold yellow]→ Reload Continue[/] (Cmd/Ctrl+Shift+P → 'Continue: Reload') to activate.\n"
    )


@connect_app.command("zed")
def cmd_connect_zed(
    repo: str = typer.Option(".", "--repo", "-r"),
    no_instructions: bool = typer.Option(False, "--no-instructions",
                                          help="Skip writing .zed/settings.json instructions"),
) -> None:
    """Wire JSAT into Zed editor as a context server + project instructions.

    Writes:
      ~/.config/zed/settings.json  — context_servers registration
      .zed/settings.json            — project-level JSAT system prompt (optional)
    """
    binary = _jsat_binary()
    repo_path = str(Path(repo).resolve())
    config_path = Path.home() / ".config" / "zed" / "settings.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)

    settings = _read_json(config_path)
    settings.setdefault("context_servers", {})
    already = "jsat" in settings["context_servers"]
    settings["context_servers"]["jsat"] = {
        "command": {"path": binary, "args": ["mcp-server", "--repo", repo_path]}
    }
    _write_json(config_path, settings)

    action = "Updated" if already else "Added"
    console.print(f"\n[green]✓[/] {action} JSAT in Zed config: [cyan]{config_path}[/]")
    console.print("[bold yellow]→ Restart Zed[/] to activate JSAT context server.\n")

    if not no_instructions:
        # Write project-level system prompt for Zed
        zed_proj = Path(repo).resolve() / ".zed" / "settings.json"
        zed_proj.parent.mkdir(parents=True, exist_ok=True)
        proj_settings = _read_json(zed_proj)
        proj_settings["assistant"] = proj_settings.get("assistant", {})
        proj_settings["assistant"]["default_model"] = proj_settings["assistant"].get(
            "default_model", {"provider": "anthropic", "model": "claude-sonnet-4-6"})
        # Write a system_prompt file that Zed will pick up
        system_md = Path(repo).resolve() / ".zed" / "JSAT.md"
        system_md.write_text(
            "# JSAT Codebase Intelligence\n\n" + _jsat_instructions_block(),
            encoding="utf-8"
        )
        _write_json(zed_proj, proj_settings)
        _print_instructions_written(
            system_md, "Zed",
            "Place this file in .zed/ — Zed picks it up as project context.",
        )


@connect_app.command("gemini")
def cmd_connect_gemini(
    repo: str = typer.Option(".", "--repo", "-r"),
    no_instructions: bool = typer.Option(False, "--no-instructions",
                                          help="Skip writing GEMINI.md"),
) -> None:
    """Wire JSAT into Google Gemini CLI as an MCP server + GEMINI.md guidance.

    Writes:
      ~/.gemini/settings.json  — MCP server registration
      GEMINI.md                — JSAT tool guidance (project root, auto-read by Gemini CLI)
    """
    _connect_mcp_tool(
        "Gemini CLI",
        Path.home() / ".gemini" / "settings.json",
        _jsat_binary(), str(Path(repo).resolve()),
        "Restart Gemini CLI",
    )
    if not no_instructions:
        gemini_md = Path(repo).resolve() / "GEMINI.md"
        _write_instructions_file(gemini_md)
        _print_instructions_written(gemini_md, "Gemini CLI",
                                    "Place this file in project root — Gemini CLI auto-reads it.")


@connect_app.command("bob")
def cmd_connect_bob(
    repo: str = typer.Option(".", "--repo", "-r"),
    scope: str = typer.Option(
        "project", "--scope", "-s",
        help="'project' → .bob/settings.json  |  'global' → ~/.bob/settings.json",
    ),
    global_: bool = typer.Option(
        False, "--global", "-g",
        help="Shorthand for --scope global — installs into ~/.bob/ for all Bob sessions",
    ),
    no_instructions: bool = typer.Option(False, "--no-instructions",
                                          help="Skip writing BOB.md"),
    install_commands: bool = typer.Option(
        True, "--install-commands/--no-commands",
        help="Also install /jsat-* slash commands in Bob Shell",
    ),
) -> None:
    """Wire JSAT into Bob Shell as an MCP server + BOB.md guidance + /jsat-* commands.

    \b
    Project level (just this repo):
        jsat connect bob

    \b
    Global (all Bob Shell sessions, one-time setup):
        jsat connect bob --global

    Writes:
      .bob/settings.json (or ~/.bob/settings.json)  — MCP server registration
      .bob/commands/jsat-*.md (or ~/.bob/commands/)  — /jsat-* slash commands
      BOB.md                                         — JSAT tool guidance (project root)
    """
    binary = _jsat_binary()
    repo_path = str(Path(repo).resolve())
    effective_scope = "global" if global_ else scope

    if effective_scope == "global":
        config_path = Path.home() / ".bob" / "settings.json"
        label = "Bob Shell (global)"
    else:
        config_path = Path.cwd() / ".bob" / "settings.json"
        label = "Bob Shell (project)"

    # Point the MCP server's AI-backed tools (jsat__query, prompt_rewrite, …) at
    # Bob itself — guaranteed available under `jsat bob`, no API key required — so
    # they work out of the box instead of falling back to the no-op provider.
    _connect_mcp_tool(label, config_path, binary, repo_path, "Restart Bob Shell",
                      env={"JSAT_AI_PROVIDER": "bob_cli"})

    if install_commands:
        cmds_dir = _write_bob_commands(effective_scope)
        console.print(
            f"[green]✓[/] Installed {len(_JSAT_SKILLS)} JSAT slash commands "
            f"in [bold]{cmds_dir}[/]\n"
            "  Type [cyan]/[/] in Bob Shell to browse them — e.g. "
            "[cyan]/jsat-query[/], [cyan]/jsat-blast-radius[/], [cyan]/jsat-security[/].\n"
        )

    if not no_instructions:
        bob_md = Path(repo).resolve() / "BOB.md"
        _write_instructions_file(bob_md)
        _print_instructions_written(bob_md, "Bob Shell",
                                    "Bob Shell reads BOB.md from the project root automatically.")


# ── All known JSAT config locations ───────────────────────────────────────────

_CONNECT_LOCATIONS: list[tuple[str, Path, str]] = [
    # (label, config_path, mcpServers_key)
    ("Claude Code (project)", Path.cwd() / ".claude" / "settings.json", "mcpServers"),
    ("Claude Code (global)",  Path.home() / ".claude" / "settings.json", "mcpServers"),
    ("Cursor",                Path.home() / ".cursor" / "mcp.json",      "mcpServers"),
    ("Codex (project)",       Path.cwd() / ".codex" / "config.json",     "mcpServers"),
    ("Codex (global)",        Path.home() / ".codex" / "config.json",    "mcpServers"),
    ("Windsurf",              Path.home() / ".codeium" / "windsurf" / "mcp_config.json", "mcpServers"),  # noqa: E501
    ("Gemini CLI",            Path.home() / ".gemini" / "settings.json", "mcpServers"),
    ("Bob Shell (project)",   Path.cwd() / ".bob" / "settings.json",     "mcpServers"),
    ("Bob Shell (global)",    Path.home() / ".bob" / "settings.json",    "mcpServers"),
]


@connect_app.command("list")
def cmd_connect_list() -> None:
    """Show all AI tools that have JSAT wired as an MCP server."""
    import json as _json
    found_any = False

    for label, path, key in _CONNECT_LOCATIONS:
        data = _read_json(path)
        jsat_cfg = data.get(key, {}).get("jsat")
        if jsat_cfg:
            found_any = True
            console.print(f"[green]✓[/] [bold]{label}[/]  ({path})")
            console.print(f"   command: {jsat_cfg.get('command')}")
            console.print(f"   args:    {jsat_cfg.get('args')}\n")

    # Continue uses an array format
    continue_path = Path.home() / ".continue" / "config.json"
    try:
        if continue_path.exists():
            cfg = _json.loads(continue_path.read_text(encoding="utf-8"))
            jsat = next((s for s in cfg.get("mcpServers", []) if s.get("name") == "jsat"), None)
            if jsat:
                found_any = True
                console.print(f"[green]✓[/] [bold]Continue.dev[/]  ({continue_path})")
                console.print(f"   command: {jsat.get('command')}\n")
    except Exception:
        pass

    # Zed uses context_servers key
    zed_path = Path.home() / ".config" / "zed" / "settings.json"
    zed_cfg = _read_json(zed_path).get("context_servers", {}).get("jsat")
    if zed_cfg:
        found_any = True
        console.print(f"[green]✓[/] [bold]Zed[/]  ({zed_path})")
        console.print(f"   command: {zed_cfg.get('command',{}).get('path')}\n")

    if not found_any:
        console.print(
            "[dim]No JSAT MCP configs found.[/]\n\n"
            "Connect to any AI tool:\n"
            "  [bold]jsat connect claude[/]     ← Claude Code (project)\n"
            "  [bold]jsat connect claude --scope global[/]  ← Claude Code (global)\n"
            "  [bold]jsat connect codex[/]      ← OpenAI Codex CLI\n"
            "  [bold]jsat connect cursor[/]     ← Cursor\n"
            "  [bold]jsat connect windsurf[/]   ← Windsurf\n"
            "  [bold]jsat connect continue[/]   ← Continue.dev\n"
            "  [bold]jsat connect zed[/]        ← Zed editor\n"
            "  [bold]jsat connect gemini[/]     ← Gemini CLI\n"
            "  [bold]jsat connect bob[/]        ← Bob Shell\n"
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

    # ── CRITICAL: route ALL logging to stderr before anything logs.
    # In stdio MCP, stdout carries ONLY JSON-RPC 2.0 messages. structlog's
    # default (and setup_logging's) PrintLoggerFactory writes to stdout, so any
    # log line corrupts the JSON-RPC stream and strict clients (e.g. Bob Shell)
    # report "MCP ERROR". Configure stderr-only logging here, before load_config
    # emits its first line.
    import logging as _logging
    import sys as _sys

    import structlog as _structlog

    _mcp_level = _logging.DEBUG if verbose else _logging.WARNING
    _logging.basicConfig(level=_mcp_level,
                         handlers=[_logging.StreamHandler(_sys.stderr)], force=True)
    _structlog.configure(
        processors=[
            _structlog.processors.add_log_level,
            _structlog.processors.TimeStamper(fmt="iso", utc=True),
            _structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=_structlog.make_filtering_bound_logger(_mcp_level),
        context_class=dict,
        logger_factory=_structlog.PrintLoggerFactory(file=_sys.stderr),
        cache_logger_on_first_use=True,
    )

    # Minimal config load — no system detection, no service pings, no indexing
    from jsat._config import load_config
    from jsat._models import JSATConfig

    cfg: JSATConfig = JSATConfig()  # safe defaults
    with contextlib.suppress(Exception):  # use defaults if config loading fails
        cfg = load_config(repo=repo_path)

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
                from jsat._config import jsat_data_dir
                from jsat._graph.sqlite import SQLiteGraph
                from jsat._models import GraphConfig
                graph_path = str(jsat_data_dir(repo_path) / "graph" / "graph.db")
                self._graph = SQLiteGraph(GraphConfig(path=graph_path))
            return self._graph

        def _get_ai(self):
            if self._ai is None:
                import os
                import shutil

                from jsat._ai.none import NoOpProvider

                # JSAT_AI_PROVIDER env var: explicitly requested provider
                # (set by `jsat connect claude` via the MCP config env block)
                _env_provider = os.environ.get("JSAT_AI_PROVIDER", "").strip()

                # Auto-detect the best available AI — same priority as auto_configure:
                # JSAT_AI_PROVIDER env > claude_cli > anthropic API > openai API > ollama > none
                def _try_claude_cli():
                    if shutil.which("claude") or _env_provider == "claude_cli":
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

                # 0. Honour explicit JSAT_AI_PROVIDER env var first
                if _env_provider == "claude_cli":
                    provider = _try_claude_cli()
                elif _env_provider and _env_provider not in ("none", ""):
                    provider = _try_provider(_env_provider) or _try_claude_cli()
                else:
                    provider = None

                # 1. Use configured provider if it actually works
                if provider is None:
                    provider = _try_provider(configured)

                # 2. Fallback chain if configured provider is unreachable
                if provider is None:
                    provider = (
                        _try_claude_cli() or
                        _try_provider("bob_cli") or
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


# ── update ─────────────────────────────────────────────────────────────────────

@app.command("update")
def cmd_update(
    pre: bool = typer.Option(False, "--pre", help="Include pre-release versions"),
) -> None:
    """Upgrade JSAT to the latest version from PyPI."""
    import subprocess
    import sys
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
            console.print("[green]✓[/] Already up to date.")
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
    from jsat.tools.knowledge_ingest import scan_repo
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


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    app()


if __name__ == "__main__":
    main()
