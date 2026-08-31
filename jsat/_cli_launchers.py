"""
jsat._cli_launchers — AI launcher commands (claude, codex, cursor, etc.)
"""
from __future__ import annotations

from pathlib import Path

import structlog
import typer

from ._cli_common import _jsat, _jsat_binary, _read_json, _write_json, app, console, err

_log = structlog.get_logger(__name__)

@app.command("shell", rich_help_panel="🤖  AI Launchers")
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


@app.command("claude", rich_help_panel="🤖  AI Launchers")
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




@app.command("bob", rich_help_panel="🤖  AI Launchers")
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

@app.command("gpt", rich_help_panel="🤖  AI Launchers")
def cmd_gpt(
    repo: str = typer.Option(".", "--repo", "-r"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Open a GPT session with JSAT tools (needs OPENAI_API_KEY)."""
    _launch_ai("gpt", repo, verbose)


@app.command(
    "ollama",
    rich_help_panel="🤖  AI Launchers",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def cmd_ollama(
    ctx: typer.Context,
    positional: str | None = typer.Argument(
        None, metavar="[TOOL|MODEL]",
        help="Shorthand: a known tool name (claude/codex/opencode) implies --tool; "
             "anything else implies --model",
    ),
    repo: str = typer.Option(".", "--repo", "-r"),
    model: str | None = typer.Option(None, "--model", "-m", help="Ollama model name"),
    tool: str | None = typer.Option(
        None, "--tool", "-t", help="Launch a coding tool through Ollama (claude, opencode, codex)"
    ),
    configure_only: bool = typer.Option(
        False, "--config", help="Configure the selected coding tool without launching it"
    ),
    restore: bool = typer.Option(
        False, "--restore", help="Remove the tool's saved Ollama-launch profile (Codex only)"
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip Ollama selectors; requires --model"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Use Ollama directly, or launch a coding tool with a local/cloud model.

    \b
    Direct JSAT shell behavior:
      jsat ai models ollama
      jsat ollama --model <model>
      jsat ollama <model>                       # shorthand for --model

    \b
    Coding tools through Ollama's official launcher:
      jsat ollama --tool claude                 # interactive model selector
      jsat ollama opencode                      # shorthand for --tool opencode
      jsat ollama --tool opencode -m qwen3.5    # local model
      jsat ollama --tool codex -m gemma4:31b-cloud  # Ollama Cloud model
      jsat ollama --tool claude -m gemma4:31b-cloud --yes -- -p "explain this repo"
      jsat ollama --tool codex --restore        # remove Codex's saved Ollama profile
    """
    if positional:
        from jsat._cli_connect import _OLLAMA_CONNECT_TOOLS

        if positional.strip().lower() in _OLLAMA_CONNECT_TOOLS:
            if tool:
                err.print("[red]choose either TOOL positional or --tool, not both.[/]")
                raise typer.Exit(1)
            tool = positional
        else:
            if model:
                err.print("[red]choose either MODEL positional or --model, not both.[/]")
                raise typer.Exit(1)
            model = positional

    if tool:
        code = _launch_with_ollama(
            tool,
            repo,
            model=model,
            configure_only=configure_only,
            restore=restore,
            yes=yes,
            passthrough=list(ctx.args),
        )
        if code:
            raise typer.Exit(code)
        return

    if configure_only or restore or yes or ctx.args:
        err.print("[red]--config, --restore, --yes, and trailing arguments require --tool.[/]")
        raise typer.Exit(1)

    from jsat.tools.shell import launch
    js = _jsat(repo=repo, verbose=verbose)
    if model is None:
        # Reuse a model already persisted via `jsat ai use ollama --model <model>`
        # before falling back to auto-selection/interactive discovery.
        cfg_ai = getattr(getattr(js, "_cfg", None), "ai", None)
        if getattr(cfg_ai, "provider", None) == "ollama":
            model = getattr(cfg_ai, "model", None)
            if model:
                console.print(f"[cyan]Using the configured Ollama model:[/] {model}")
    if model is None:
        from jsat._ollama import (
            discover_ollama_models,
            model_selection_help,
            select_ollama_model,
        )

        try:
            model = select_ollama_model(None, discover_ollama_models())
            console.print(f"[cyan]Using the only registered Ollama model:[/] {model}")
        except Exception as exc:
            err.print(
                f"[yellow]Choose an Ollama model for the direct JSAT shell.[/]\n"
                f"{exc}\n{model_selection_help()}"
            )
            raise typer.Exit(1) from exc
    js.switch_ai("ollama", model=model)
    launch(js)


def _load_ollama_tool_model(tool: str) -> str | None:
    """Return the model persisted by `jsat connect ollama <tool> --model <model>`.

    Reads the global config directly rather than building a full `JSAT` instance —
    this launcher has no project-repo dependency today, and `connect ollama`
    deliberately writes global scope only.
    """
    import yaml

    cfg_path = Path.home() / ".jsat" / "config.yaml"
    if not cfg_path.exists():
        return None
    try:
        data = yaml.safe_load(cfg_path.read_text()) or {}
    except Exception:
        return None
    return data.get("ai", {}).get("ollama_tool_models", {}).get(tool.strip().lower())


def _launch_with_ollama(
    tool: str,
    repo: str,
    *,
    model: str | None,
    configure_only: bool,
    restore: bool = False,
    yes: bool,
    passthrough: list[str],
) -> int:
    """Delegate coding-tool configuration and launch to the Ollama CLI."""
    import shutil
    import subprocess

    from jsat._ollama import build_ollama_launch_args, ollama_model_kind

    if model is None and not restore:
        remembered = _load_ollama_tool_model(tool)
        if remembered:
            model = remembered
            console.print(f"[cyan]Using the model connected for this tool:[/] {model}")

    ollama_bin = shutil.which("ollama")
    if not ollama_bin:
        err.print(
            "[red]ollama not found in PATH.[/]\n"
            "  Install it from [bold]https://ollama.com/download[/]"
        )
        raise typer.Exit(1)

    try:
        args = build_ollama_launch_args(
            tool,
            model=model,
            configure_only=configure_only,
            restore=restore,
            yes=yes,
            passthrough=passthrough,
        )
    except ValueError as exc:
        err.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc

    if restore:
        console.print(f"[cyan]Removing[/] the saved {tool} Ollama-launch profile.")
    elif model:
        kind = ollama_model_kind(model)
        detail = "runs on this machine" if kind == "local" else "runs through Ollama Cloud"
        console.print(f"[cyan]{kind.title()} model:[/] [bold]{model}[/] ({detail})")
        if kind == "cloud":
            console.print("[dim]If needed, authenticate first with `ollama signin`.[/dim]")
    else:
        console.print("[cyan]Model:[/] choose local or cloud in Ollama's selector")

    repo_abs = str(Path(repo).resolve())
    if tool.strip().lower() == "opencode" and not restore:
        _auto_connect("opencode", repo_abs)
    console.print(f"[green]✓[/] Running [bold]ollama {' '.join(args[:2])}[/] in {repo_abs}\n")
    result = subprocess.run([ollama_bin, *args], cwd=repo_abs)
    return result.returncode


# ── AI tool launchers (parity with `jsat claude`) ────────────────────────────

def _tool_install_hint(tool: str) -> str:
    """Return OS-appropriate install instructions for an AI tool."""
    import platform
    system = platform.system()  # "Darwin" | "Linux" | "Windows"
    hints: dict[str, dict[str, str]] = {
        "codex": {
            "Darwin":  "curl -fsSL https://chatgpt.com/codex/install.sh | sh",
            "Linux":   "curl -fsSL https://chatgpt.com/codex/install.sh | sh",
            "Windows": "install Codex from ChatGPT desktop or see OpenAI Codex CLI docs",
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
    "codex":    (Path.home() / ".codex" / "config.toml",         "mcpServers"),
    "opencode": (Path.home() / ".config" / "opencode" / "opencode.json", "mcp"),
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
    if tool == "opencode":
        from jsat._cli_connect import _opencode_commands_dir, _opencode_config_path

        config_path = _opencode_config_path()
        commands_ready = (_opencode_commands_dir() / "jsat.md").exists()
        return "jsat" in _read_json(config_path).get(key, {}) and commands_ready
    if tool == "codex":
        from jsat._cli_connect import _has_current_codex_jsat_mcp
        skill_file = config_path.parent / "skills" / "jsat" / "SKILL.md"
        return _has_current_codex_jsat_mcp(config_path) and skill_file.exists()
    return "jsat" in _read_json(config_path).get(key, {})


def _auto_connect(tool: str, repo: str) -> None:
    """Silently connect JSAT to a tool if not already wired."""
    # OpenCode entries created by older JSAT versions need their provider marker
    # repaired, and slash-command files may have been removed independently.
    if _is_connected(tool) and tool != "opencode":
        return
    # Deferred imports to avoid circular imports with _cli_connect
    from jsat._cli_connect import (
        _connect_codex_mcp,
        _connect_mcp_tool,
        _connect_opencode_mcp,
        _install_opencode_commands,
        _opencode_config_path,
        _write_instructions_file,
    )
    from jsat._cli_skills_data import _write_codex_skill
    console.print(f"[dim]Auto-connecting JSAT to {tool}...[/dim]")
    binary = _jsat_binary()
    repo_path = str(Path(repo).resolve())
    config_path, key = _TOOL_CONFIG_PATHS[tool]
    if tool == "opencode":
        config_path = _opencode_config_path()
    if tool == "codex":
        _connect_codex_mcp(
            config_path,
            binary,
            env={"JSAT_AI_PROVIDER": "codex_cli", "JSAT_MCP_ALLOW_INSECURE": "1"},
        )
        _write_codex_skill(config_path.parent / "skills" / "jsat")
    elif tool == "opencode":
        try:
            _connect_opencode_mcp(config_path, binary)
        except ValueError as exc:
            err.print(f"[red]{exc}[/]")
            raise typer.Exit(1) from exc
        _install_opencode_commands()
    elif key == "context_servers":
        settings = _read_json(config_path)
        settings.setdefault("context_servers", {})
        settings["context_servers"]["jsat"] = {
            "command": {"path": binary, "args": ["mcp-server", "--repo", repo_path]}
        }
        _write_json(config_path, settings)
    else:
        _connect_mcp_tool(tool.title(), config_path, binary, repo_path, f"Restart {tool.title()}")
    # Also write guidance file
    if tool == "cursor":
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


@app.command(
    "codex",
    rich_help_panel="🤖  AI Launchers",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def cmd_codex(
    ctx: typer.Context,
    repo: str = typer.Option(".", "--repo", "-r", help="Repository root"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Open Codex CLI with JSAT tools pre-configured.

    \b
    Auto-connects JSAT if not already done, then launches:
      codex        (reads ~/.codex/config.toml automatically)
      codex resume <session-id>

    \b
    JSAT MCP tools are available to Codex immediately. No project files are generated;
    Codex runs in the repo directory passed with --repo.
    Install Codex: curl -fsSL https://chatgpt.com/codex/install.sh | sh
    """
    _launch_tool("codex", "codex", repo, extra_args=list(ctx.args))


@app.command("cursor", rich_help_panel="🤖  AI Launchers")
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


@app.command("windsurf", rich_help_panel="🤖  AI Launchers")
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


@app.command("gemini", rich_help_panel="🤖  AI Launchers")
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


@app.command("zed", rich_help_panel="🤖  AI Launchers")
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
