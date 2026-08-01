"""
jsat._cli_connect — Connect subcommands (jsat connect <tool>).
"""
from __future__ import annotations

import json
from pathlib import Path

import structlog
import typer

from ._cli_common import (
    _jsat_binary,
    _read_json,
    _write_json,
    app,
    connect_app,
    console,
    err,
)
from ._cli_skills_data import _JSAT_SKILLS, _write_bob_commands, _write_jsat_dispatcher

_log = structlog.get_logger(__name__)

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
    _ai_env: dict[str, str] = {
        # Silences the "no auth configured" startup warning for local/dev use.
        # Remove this and set JSAT_MCP_TOKEN or JSAT_MCP_TOKEN_ROLES for auth enforcement.
        "JSAT_MCP_ALLOW_INSECURE": "1",
    }
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
        skills_dir = _write_jsat_dispatcher(effective_scope)
        console.print(
            f"[green]✓[/] Installed [cyan]/jsat[/] dispatcher "
            f"({len(_JSAT_SKILLS)} subcommands) in [bold]{skills_dir}[/]\n"
            "\n[bold]Usage:[/] [cyan]/jsat <command> [flags] [args][/]\n"
            "  [cyan]/jsat help[/]             — list all subcommands\n"
            "  [cyan]/jsat query[/] <question> — answer codebase questions\n"
            "  [cyan]/jsat crack[/] <task>     — multi-agent war room\n"
            "  [cyan]/jsat lazy[/] <task>      — reuse-first planning\n"
            "  [cyan]/jsat aw[/] <task>        — workflow advisor\n"
            "  [cyan]/jsat security[/] [path]  — security scan\n"
            "  [cyan]/jsat blast[/] <target>   — blast radius analysis\n"
            "  [cyan]/jsat review[/] <diff>    — multi-model code review\n"
            f"  ... {len(_JSAT_SKILLS)} total — type [cyan]/jsat help[/] to see all\n"
        )

    console.print(
        "[bold yellow]→ Restart Claude Code[/] to activate.\n"
        "  MCP tools: [dim]jsat__query · jsat__blast_radius · jsat__security_review ·[/]\n"
        "             [dim]jsat__investigate_incident · jsat__index_repo · ...[/]\n"
        "  Slash cmd:  [dim]/jsat <command>[/]\n"
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
                      env={"JSAT_AI_PROVIDER": "bob_cli", "JSAT_MCP_ALLOW_INSECURE": "1"})

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
