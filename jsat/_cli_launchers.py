"""
jsat._cli_launchers — AI launcher commands (claude, codex, cursor, etc.)
"""
from __future__ import annotations

import contextlib
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


@app.command("ollama", rich_help_panel="🤖  AI Launchers")
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
    # Deferred imports to avoid circular imports with _cli_connect
    from jsat._cli_connect import _connect_mcp_tool, _write_instructions_file
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


@app.command("codex", rich_help_panel="🤖  AI Launchers")
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
