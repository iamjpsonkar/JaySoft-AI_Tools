"""
jsat._cli_connect — Connect subcommands (jsat connect <tool>).
"""
from __future__ import annotations

import json
from pathlib import Path

import structlog
import typer

from ._cli_common import (
    ConfigParseError,
    _jsat_binary,
    _read_json,
    _read_json_or_abort,
    _write_json,
    connect_app,
    console,
    err,
)
from ._cli_skills_data import (
    _JSAT_SKILLS,
    _write_bob_commands,
    _write_codex_skill,
    _write_jsat_dispatcher,
)

_log = structlog.get_logger(__name__)

_OLLAMA_CONNECT_TOOLS = ("claude", "codex", "opencode")


def _persist_ai_provider_if_default(cfg_path: Path, provider: str) -> None:
    """Write `ai.provider` into cfg_path, but only if it's still the factory
    default ("ollama") or unset — never overwrite a provider the user already
    chose explicitly (e.g. via `jsat ai use anthropic`)."""
    import yaml

    existing: dict = {}
    if cfg_path.exists():
        try:
            existing = yaml.safe_load(cfg_path.read_text()) or {}
        except Exception:
            return  # don't clobber a config file we can't parse

    current = existing.get("ai", {}).get("provider")
    if current not in (None, "ollama"):
        return

    existing.setdefault("ai", {})
    existing["ai"]["provider"] = provider
    existing["ai"].pop("model", None)  # native CLIs use their own default model

    try:
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        with cfg_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(existing, f, sort_keys=False)
    except OSError as exc:
        # The MCP/client connection is still useful when the optional provider
        # preference cannot be persisted (read-only home, sandbox, kiosk install).
        # Do not turn a successful connection into a launcher failure.
        _log.warning(
            "ai_provider_persist_failed",
            path=str(cfg_path),
            error_type=type(exc).__name__,
        )


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
    write_claude_md: bool = typer.Option(
        True, "--claude-md/--no-claude-md",
        help="Also write JSAT guidance into CLAUDE.md so Claude reaches for JSAT "
             "without being asked (slash commands alone are opt-in)",
    ),
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
    settings = _read_json_or_abort(settings_path)

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
        # JSAT_AI_PROVIDER only reaches the live MCP server process — it does
        # nothing for `jsat doctor`/`jsat ai status` invoked from a plain shell,
        # and is silently dropped if the MCP client caches an older process
        # without it. Persist the same choice to the on-disk config so every
        # entry point (CLI, MCP server, doctor) agrees, unless the user already
        # made an explicit choice (anything other than the untouched "ollama"
        # factory default).
        _persist_ai_provider_if_default(
            Path.home() / ".jsat" / "config.yaml" if effective_scope == "global"
            else Path(repo_path) / ".jsat" / "config.yaml",
            "claude_cli",
        )
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

    # CLAUDE.md is loaded automatically every session, so this is what makes Claude
    # reach for JSAT unprompted — slash commands only fire when the user types one.
    if write_claude_md:
        claude_md = (Path.home() if effective_scope == "global" else Path(repo).resolve()) \
            / "CLAUDE.md"
        _write_instructions_file(claude_md)
        _print_instructions_written(
            claude_md, "Claude Code",
            "Claude now suggests JSAT tools proactively and reports what each one "
            "found. Remove with: jsat disconnect claude",
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
    settings = _read_json_or_abort(config_path)
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


def _opencode_config_path() -> Path:
    """Return OpenCode's global JSON config path, respecting XDG_CONFIG_HOME."""
    import os

    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg_config).expanduser() if xdg_config else Path.home() / ".config"
    return base / "opencode" / "opencode.json"


def _opencode_commands_dir() -> Path:
    """Return OpenCode's global custom-command directory."""
    return _opencode_config_path().parent / "commands"


def _install_opencode_commands() -> Path:
    """Install JSAT's /jsat dispatcher in OpenCode's global command registry."""
    return _write_jsat_dispatcher("global", commands_dir=_opencode_commands_dir())


def _connect_opencode_mcp(config_path: Path, binary: str) -> bool:
    """Upsert JSAT using OpenCode's native local-MCP configuration shape."""
    import json

    if config_path.exists():
        try:
            settings = json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ValueError(
                f"OpenCode config is not valid JSON; JSAT left it unchanged: {config_path}"
            ) from exc
    else:
        settings = {}
    settings.setdefault("$schema", "https://opencode.ai/config.json")
    settings.setdefault("mcp", {})
    already = "jsat" in settings["mcp"]
    settings["mcp"]["jsat"] = {
        "type": "local",
        # No --repo pin: OpenCode starts local MCP servers in the active workspace.
        "command": [binary, "mcp-server"],
        "enabled": True,
        "environment": {
            "JSAT_AI_PROVIDER": "opencode_cli",
            "JSAT_MCP_ALLOW_INSECURE": "1",
        },
    }
    _write_json(config_path, settings)
    # OpenCode starts local MCP servers in whatever workspace is active, not a
    # fixed repo pinned at connect time — persist to the global config, which
    # load_config() falls back to when no repo-local one exists.
    _persist_ai_provider_if_default(Path.home() / ".jsat" / "config.yaml", "opencode_cli")
    return already


@connect_app.command("opencode")
def cmd_connect_opencode(
    show: bool = typer.Option(False, "--show", help="Print the config that was written"),
    install_commands: bool = typer.Option(
        True,
        "--install-commands/--no-commands",
        help="Also install /jsat and /jsat-help in OpenCode",
    ),
) -> None:
    """Wire JSAT MCP and slash commands into OpenCode.

    \b
    OpenCode does not need to be installed separately:
      jsat connect opencode
      jsat ollama --tool opencode

    The global config is deep-merged with Ollama's temporary model configuration.
    """
    import json

    config_path = _opencode_config_path()
    binary = _jsat_binary()
    try:
        already = _connect_opencode_mcp(config_path, binary)
    except ValueError as exc:
        err.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    action = "Updated" if already else "Added"
    console.print(
        f"\n[green]✓[/] {action} JSAT MCP server in [bold]OpenCode[/]\n"
        f"  Binary : [cyan]{binary}[/]\n"
        f"  Config : [cyan]{config_path}[/]\n"
    )
    if show:
        entry = _read_json_or_abort(config_path)["mcp"]["jsat"]
        console.print_json(json.dumps({"mcp": {"jsat": entry}}, indent=2))
    if install_commands:
        commands_dir = _install_opencode_commands()
        console.print(
            f"[green]✓[/] Installed [cyan]/jsat[/] and [cyan]/jsat-help[/] "
            f"in [bold]{commands_dir}[/]\n"
        )
    console.print(
        "[bold yellow]→ Start OpenCode[/] directly or with "
        "[bold]jsat ollama --tool opencode[/].\n"
    )


def _resolve_ollama_connect_target(target: str, tool: str | None) -> str:
    """Resolve the Ollama connector's option and ``tool=name`` compatibility syntax."""
    positional = target.strip().lower()
    if positional.startswith("tool="):
        positional = positional.partition("=")[2].strip()
    selected = tool.strip().lower() if tool else positional
    if tool and positional != "all":
        raise ValueError("choose either TOOL/tool=TOOL or --tool, not both")
    if selected not in (*_OLLAMA_CONNECT_TOOLS, "all"):
        choices = " | ".join((*_OLLAMA_CONNECT_TOOLS, "all"))
        raise ValueError(f"unsupported Ollama connection target {selected!r}; choose: {choices}")
    return selected


def _persist_ollama_tool_model(tool: str, model: str) -> Path:
    """Remember the model `jsat ollama --tool <tool>` should default to.

    Written to the global config (mirroring `cmd_ai_use`'s read/update/write
    pattern in `_cli_ai.py`) since `connect ollama` itself only writes global
    client configs.
    """
    import yaml

    cfg_path = Path.home() / ".jsat" / "config.yaml"
    existing: dict = {}
    if cfg_path.exists():
        try:
            existing = yaml.safe_load(cfg_path.read_text()) or {}
        except Exception:
            existing = {}
    existing.setdefault("ai", {}).setdefault("ollama_tool_models", {})[tool] = model
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with cfg_path.open("w") as f:
        yaml.dump(existing, f, default_flow_style=False, sort_keys=False)
    return cfg_path


def _connect_ollama_target(target: str, show: bool) -> None:
    """Configure one client that JSAT knows Ollama can launch."""
    if target == "claude":
        cmd_connect_claude(
            scope="global",
            global_=True,
            repo=".",
            install_skills=True,
            show=show,
            write_claude_md=True,
        )
    elif target == "codex":
        cmd_connect_codex(
            repo=".", scope="global", global_=True, no_instructions=False
        )
    else:
        cmd_connect_opencode(show=show, install_commands=True)


@connect_app.command("ollama")
def cmd_connect_ollama(
    target: str = typer.Argument(
        "all",
        metavar="[TOOL|tool=TOOL]",
        help="Supported Ollama-launched client; default: all",
    ),
    tool: str | None = typer.Option(
        None, "--tool", "-t", help="Equivalent to the positional TOOL selector"
    ),
    model: str | None = typer.Option(
        None, "--model", "-m",
        help="Remember this model as the default for `jsat ollama --tool TOOL` (single TOOL only)",
    ),
    show: bool = typer.Option(False, "--show", help="Print configs where supported"),
) -> None:
    """Connect JSAT to clients launched through Ollama.

    Ollama selects and supplies the model; the launched client still owns its MCP
    configuration. Direct and Ollama-launched copies therefore use the same config.

    \b
      jsat connect ollama
      jsat connect ollama --tool opencode
      jsat connect ollama tool=opencode
      jsat connect ollama tool=opencode --model gemma4:31b-cloud
    """
    try:
        selected = _resolve_ollama_connect_target(target, tool)
    except ValueError as exc:
        err.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc

    if model and selected == "all":
        err.print("[red]--model requires a single TOOL target, not all.[/]")
        raise typer.Exit(1)

    targets = _OLLAMA_CONNECT_TOOLS if selected == "all" else (selected,)
    failures: list[str] = []
    for name in targets:
        console.print(f"\n[bold]Connecting Ollama-launched {name}…[/]")
        try:
            _connect_ollama_target(name, show)
        except (Exception, typer.Exit) as exc:
            failures.append(name)
            err.print(f"[red]Could not connect {name}:[/] {exc}")
            if selected != "all":
                raise typer.Exit(1) from exc

    if failures:
        err.print(
            "[yellow]Connected the remaining tools; failed: "
            + ", ".join(failures)
            + "[/]"
        )
        raise typer.Exit(1)

    if model:
        cfg_path = _persist_ollama_tool_model(selected, model)
        console.print(
            f"[green]✓[/] Ollama-launched [bold]{selected}[/] will default to model "
            f"[bold]{model}[/] (saved to [cyan]{cfg_path}[/]).\n"
            f"  Bare [bold]jsat ollama --tool {selected}[/] now reuses it."
        )

    console.print(
        "\n[green]✓[/] Ollama connection setup complete. "
        "Choose the tool and model with [bold]ollama[/] or [bold]jsat ollama --tool TOOL[/]."
    )


def _toml_dq(value: str) -> str:
    """Double-quote a TOML string value."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _toml_array(values: list[str]) -> str:
    return "[" + ", ".join(_toml_dq(v) for v in values) + "]"


def _toml_inline_map(values: dict[str, str]) -> str:
    inner = ", ".join(f"{k} = {_toml_dq(v)}" for k, v in sorted(values.items()))
    return "{ " + inner + " }"


def _remove_toml_table_block(text: str, table: str) -> tuple[str, bool]:
    """Remove a top-level TOML table and any nested subtables with the same prefix."""
    lines = text.splitlines()
    out: list[str] = []
    removed = False
    skipping = False
    table_header = f"[{table}]"
    nested_prefix = f"[{table}."

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if stripped == table_header or stripped.startswith(nested_prefix):
                skipping = True
                removed = True
                continue
            skipping = False
        if not skipping:
            out.append(line)

    cleaned = "\n".join(out).rstrip()
    return cleaned, removed


def _toml_table_block(text: str, table: str) -> str | None:
    lines = text.splitlines()
    out: list[str] = []
    collecting = False
    table_header = f"[{table}]"
    nested_prefix = f"[{table}."

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if stripped == table_header or stripped.startswith(nested_prefix):
                collecting = True
            elif collecting:
                break
        if collecting:
            out.append(line)

    return "\n".join(out) if out else None


def _write_toml_mcp_server(
    config_path: Path,
    server_name: str,
    *,
    command: str | None = None,
    args: list[str] | None = None,
    env: dict[str, str] | None = None,
    env_vars: list[str] | None = None,
    url: str | None = None,
) -> bool:
    """Upsert a Codex `[mcp_servers.<name>]` table. Returns True if it existed."""
    table = f"mcp_servers.{server_name}"
    existing = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    cleaned, already = _remove_toml_table_block(existing, table)

    lines = [f"[{table}]"]
    if command is not None:
        lines.append(f"command = {_toml_dq(command)}")
    if args:
        lines.append(f"args = {_toml_array(args)}")
    if url is not None:
        lines.append(f"url = {_toml_dq(url)}")
    if env:
        lines.append(f"env = {_toml_inline_map(env)}")
    if env_vars:
        lines.append(f"env_vars = {_toml_array(env_vars)}")

    updated = (cleaned + "\n\n" if cleaned else "") + "\n".join(lines) + "\n"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(updated, encoding="utf-8")
    return already


def _remove_toml_mcp_server(config_path: Path, server_name: str) -> bool:
    """Remove a Codex MCP server table from config.toml."""
    if not config_path.exists():
        return False
    table = f"mcp_servers.{server_name}"
    updated, removed = _remove_toml_table_block(config_path.read_text(encoding="utf-8"), table)
    if removed:
        config_path.write_text((updated.rstrip() + "\n") if updated else "", encoding="utf-8")
    return removed


def _has_toml_mcp_server(config_path: Path, server_name: str) -> bool:
    if not config_path.exists():
        return False
    text = config_path.read_text(encoding="utf-8")
    return f"[mcp_servers.{server_name}]" in text


def _has_current_codex_jsat_mcp(config_path: Path) -> bool:
    if not config_path.exists():
        return False
    block = _toml_table_block(config_path.read_text(encoding="utf-8"), "mcp_servers.jsat")
    return bool(block and 'args = ["mcp-server"]' in block and "--repo" not in block)


def _codex_jsat_config_path() -> Path:
    return Path.home() / ".codex" / "config.toml"


def _codex_jsat_skill_dir() -> Path:
    return Path.home() / ".codex" / "skills" / "jsat"


def _connect_codex_mcp(
    config_path: Path,
    binary: str,
    *,
    server_name: str = "jsat",
    env: dict[str, str] | None = None,
) -> bool:
    already = _write_toml_mcp_server(
        config_path,
        server_name,
        command=binary,
        args=["mcp-server"],
        env=env,
    )
    provider = (env or {}).get("JSAT_AI_PROVIDER")
    if provider:
        # Codex resolves its repo from cwd at launch time, not connect time, so
        # there's no fixed per-repo config.yaml — persist to the global config,
        # which load_config() falls back to when no repo-local one exists.
        _persist_ai_provider_if_default(Path.home() / ".jsat" / "config.yaml", provider)
    return already


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


_GITHUB_MCP_IMAGE = "ghcr.io/github/github-mcp-server"
_GITHUB_MCP_REMOTE = "https://api.githubcopilot.com/mcp/"

# Where each AI tool keeps its MCP server map. Same files `jsat connect <tool>`
# already writes, so JSAT and GitHub end up side by side.
_MCP_CONFIG_PATHS: dict[str, tuple[str, str]] = {
    # tool -> (project-scope path, global-scope path) relative to cwd / home
    "claude":   (".claude/settings.json",  ".claude/settings.json"),
    "cursor":   (".cursor/mcp.json",       ".cursor/mcp.json"),
    "codex":    (".codex/config.toml",     ".codex/config.toml"),
    "bob":      (".bob/settings.json",     ".bob/settings.json"),
    "windsurf": (".codeium/windsurf/mcp_config.json", ".codeium/windsurf/mcp_config.json"),
    "gemini":   (".gemini/settings.json",  ".gemini/settings.json"),
}


@connect_app.command("github")
def cmd_connect_github(
    tool: str = typer.Argument(
        "claude", help="AI tool to wire GitHub into: claude | cursor | codex | bob "
                       "| windsurf | gemini",
    ),
    scope: str = typer.Option(
        "project", "--scope", "-s", help="'project' (this repo) | 'global' (all projects)",
    ),
    global_: bool = typer.Option(False, "--global", "-g", help="Shorthand for --scope global"),
    remote: bool = typer.Option(
        False, "--remote",
        help="Use GitHub's hosted MCP endpoint instead of the local Docker image",
    ),
    token_env: str = typer.Option(
        "GITHUB_PERSONAL_ACCESS_TOKEN", "--token-env",
        help="Name of the env var holding your PAT. The VALUE is never written to disk.",
    ),
    repo: str = typer.Option(".", "--repo", "-r"),
) -> None:
    """Wire the GitHub MCP server in alongside JSAT, so errors become fixes.

    \b
    JSAT tells the AI what broke and where (graph, blast radius, improve bundles).
    GitHub tells it whether anyone has hit this before. Together the AI can search
    existing issues, read the PR that introduced a regression, and file a report
    with real context instead of a guess.

    \b
    jsat connect github                  Docker image, Claude Code, this repo
    jsat connect github cursor --global  Cursor, all projects
    jsat connect github --remote         GitHub's hosted endpoint (no Docker)

    \b
    Your token is read from the environment at run time by the MCP client — only
    the variable NAME is written into the config file, never the token itself.
    Needs `repo` scope (add `read:org` for org-wide issue search).
    """
    import os
    import re
    import shutil as _shutil

    tool_key = tool.strip().lower()

    # Security: token_env is later interpolated into a literal `sh -c "..."` string
    # written to disk (Codex's config.toml) and executed whenever Codex launches
    # the MCP server. It must be a bare environment-variable NAME — never free-form
    # text — so reject anything containing shell metacharacters outright rather
    # than trying to safely quote it.
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token_env):
        err.print(
            f"[bold red]Invalid --token-env value:[/] {token_env!r}\n"
            "  Must be a valid environment variable name: letters, digits, "
            "underscore, not starting with a digit (e.g. GITHUB_PERSONAL_ACCESS_TOKEN)."
        )
        raise typer.Exit(1)

    if tool_key not in _MCP_CONFIG_PATHS:
        from jsat._ai.aliases import suggest
        err.print(f"[red]Unknown tool:[/] {tool}")
        close = suggest(tool_key, list(_MCP_CONFIG_PATHS))
        if close:
            err.print(f"Did you mean [bold]jsat connect github {close[0]}[/]?")
        err.print("Supported: " + " | ".join(_MCP_CONFIG_PATHS))
        raise typer.Exit(1)

    effective_scope = "global" if global_ else scope
    project_rel, global_rel = _MCP_CONFIG_PATHS[tool_key]
    if tool_key == "codex":
        effective_scope = "global"
        config_path = _codex_jsat_config_path()
    else:
        config_path = (
            Path.home() / global_rel if effective_scope == "global"
            else Path(repo).resolve() / project_rel
        )

    if remote:
        entry: dict = {"type": "http", "url": _GITHUB_MCP_REMOTE}
        transport = f"hosted endpoint ({_GITHUB_MCP_REMOTE})"
    else:
        if not _shutil.which("docker"):
            console.print(
                "[yellow]⚠[/] Docker was not found on PATH. The local GitHub MCP server "
                "runs as a container.\n"
                "  Install Docker, or use the hosted endpoint: "
                "[bold]jsat connect github --remote[/]\n"
            )
        entry = {
            "command": "docker",
            "args": [
                "run", "-i", "--rm",
                "-e", "GITHUB_PERSONAL_ACCESS_TOKEN",
                _GITHUB_MCP_IMAGE,
            ],
            # Name only — the client expands this from its own environment.
            "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": f"${{{token_env}}}"},
        }
        transport = f"local container ({_GITHUB_MCP_IMAGE})"

    if tool_key == "codex":
        if remote:
            already = _write_toml_mcp_server(config_path, "github", url=_GITHUB_MCP_REMOTE)
        else:
            if token_env == "GITHUB_PERSONAL_ACCESS_TOKEN":
                command = "docker"
                args = [
                    "run", "-i", "--rm",
                    "-e", "GITHUB_PERSONAL_ACCESS_TOKEN",
                    _GITHUB_MCP_IMAGE,
                ]
                env_vars = [token_env]
            else:
                command = "sh"
                args = [
                    "-c",
                    "exec docker run -i --rm "
                    f"-e GITHUB_PERSONAL_ACCESS_TOKEN=\"${{{token_env}}}\" "
                    f"{_GITHUB_MCP_IMAGE}",
                ]
                env_vars = [token_env]
            already = _write_toml_mcp_server(
                config_path, "github", command=command, args=args, env_vars=env_vars
            )
        settings = {}
        has_jsat = _has_toml_mcp_server(config_path, "jsat")
    else:
        settings = _read_json_or_abort(config_path)
        settings.setdefault("mcpServers", {})
        already = "github" in settings["mcpServers"]
        settings["mcpServers"]["github"] = entry
        _write_json(config_path, settings)
        has_jsat = "jsat" in settings.get("mcpServers", {})

    action = "Updated" if already else "Added"
    console.print(
        f"\n[green]✓[/] {action} GitHub MCP server for [bold]{tool_key}[/] "
        f"({effective_scope})"
    )
    console.print(f"  Transport : [cyan]{transport}[/]")
    console.print(f"  Config    : [cyan]{config_path}[/]")
    console.print(f"  Token from: [cyan]${token_env}[/] [dim](name only — value never stored)[/]\n")

    if not os.environ.get(token_env):
        console.print(
            f"[yellow]⚠[/] [bold]${token_env}[/] is not set in this shell.\n"
            f"  export {token_env}=ghp_...   [dim](needs `repo` scope)[/]\n"
        )

    if not has_jsat:
        console.print(
            "[dim]Tip: JSAT is not wired into this config yet — "
            f"run [bold]jsat connect {tool_key}[/] so the AI has both.[/]\n"
        )

    console.print(
        f"[bold yellow]→ Restart {tool_key}[/] to activate.\n"
        "  The AI can now search issues, read PRs, and file a report straight from a "
        "[bold]jsat improve[/] bundle.\n"
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

### Self-improvement
- `jsat__improve_status` — friction JSAT has recorded in itself (read-only)

## Reach for JSAT FIRST — this is not optional

This repository is indexed in a JSAT graph. The graph knows things grep and file
reading cannot: who calls what, what breaks downstream, which paths are untested,
which endpoints lack auth. **Use it before falling back to generic tools.**

Apply this rule on every turn, without being asked:

| The user asks… | Call this FIRST | Not this |
|---|---|---|
| "what does X do?" / "where is X?" | `jsat__query`, `jsat__get_function` | random grep |
| "what calls X?" / "what breaks if I change it?" | `jsat__trace_call_chain` | guessing |
| anything before an edit to shared code | `jsat__blast_radius` | editing and hoping |
| "is this secure?" / auth questions | `jsat__security_review` | eyeballing the code |
| "what should I test?" | `jsat__get_test_gaps` | writing tests blind |
| a DB migration | `jsat__validate_migration` | reading the SQL |
| "why did this break?" | `jsat__investigate_incident` | scanning git log |
| a big or risky design decision | `jsat__crack`, `jsat__ithinking_plan` | answering off the cuff |
| context is getting long | `jsat__token_compress` | truncating arbitrarily |

**Suggest JSAT proactively.** When a user is about to do something JSAT covers,
say so before they ask — e.g. "before that refactor, let me check the blast radius"
or "there's a `/jsat security` scan that would catch this class of bug".

Useful shell commands to recommend (they are not MCP tools):
- `jsat session list` / `jsat session resume` — resume an interrupted skill run
- `jsat note add "…"` / `jsat note search …` — capture and recall project knowledge
- `jsat improve` — let JSAT diagnose a problem it hit in itself and draft a fix
- `jsat index .` — refresh the graph after significant code changes

## After using a JSAT tool, say what it bought you

Every time you call a `jsat__*` tool, close the loop with ONE short line telling
the user what the graph gave you that they would otherwise have had to dig for.
Be concrete and honest — cite the actual numbers or names returned.

Good:
- "`jsat__blast_radius` found 12 downstream callers, 3 breaking — that's why I'm
  changing the signature additively instead."
- "`jsat__get_test_gaps` showed `refund()` has no test covering the timeout path,
  so I wrote that one first."
- "`jsat__query` answered this from the index in one call — no file hunting needed."

Avoid:
- Praising the tool for its own sake, or repeating this line when the tool
  returned nothing useful. If a tool added no value, say that plainly instead.

If the graph is empty or stale, tell the user to run `jsat index .` rather than
silently falling back to grep.

## When something breaks: pair JSAT with GitHub MCP

If a `github` MCP server is also connected (`jsat connect github`), use the two
together. JSAT knows what broke *in this codebase*; GitHub knows whether anyone
has hit it before. Neither is much use alone.

On any error, stack trace, or failing test the user shares:

1. **Locate it locally first** — `jsat__query` / `jsat__get_function` to find the
   code, `jsat__blast_radius` to see what else the fix would touch. Never open a
   GitHub issue about code you have not read.
2. **Check whether it is known** — search the GitHub MCP server for issues and PRs
   matching the exception type and the JSAT-internal frame (e.g.
   `IndexNotFound jsat/_core.py`). Report the issue number and status if you find
   one, and stop: the answer may already be there.
3. **Find what changed** — if it is a regression, use `jsat__get_recent_changes`
   for local commits and GitHub MCP to read the PR that introduced the change.
4. **Report only if genuinely new.** Run `jsat improve` to produce a bundle
   (diagnosis + patch + privacy-filtered issue body), then file the issue through
   GitHub MCP using `issue.md` from that bundle as the body.

Rules that are not optional:
- **Never paste raw errors, paths, or code from the user's project into GitHub.**
  A `jsat improve` bundle is already privacy-filtered; a raw traceback is not.
- **Search before filing.** Duplicate issues cost maintainers more than silence.
- **Ask before writing anything public** — creating an issue, comment, or PR is
  outward-facing and hard to undo. Reading is fine unprompted; writing is not.
"""


@connect_app.command("codex")
def cmd_connect_codex(
    repo: str = typer.Option(".", "--repo", "-r"),
    scope: str = typer.Option(
        "global", "--scope", "-s",
        help="Deprecated compatibility option; Codex uses ~/.codex/config.toml",
    ),
    global_: bool = typer.Option(
        False, "--global", "-g",
        help="Deprecated compatibility option; Codex config is always global",
    ),
    no_instructions: bool = typer.Option(
        False, "--no-instructions",
        help="Skip installing the global $jsat Codex skill",
    ),
) -> None:
    """Wire JSAT into OpenAI Codex CLI as a global MCP server and skill.

    \b
    One-time setup:
        jsat connect codex

    \b
    No project files are generated. Codex resolves the repo from the directory
    where Codex runs, so start Codex in the target repo or use `jsat codex --repo`.

    Writes global Codex files:
      ~/.codex/config.toml             — MCP server registration
      ~/.codex/skills/jsat/SKILL.md    — $jsat command dispatcher
    """
    binary = _jsat_binary()
    _ = (repo, scope, global_)
    config_path = _codex_jsat_config_path()
    env = {"JSAT_AI_PROVIDER": "codex_cli", "JSAT_MCP_ALLOW_INSECURE": "1"}
    already = _connect_codex_mcp(config_path, binary, env=env)
    skill_dir: Path | None = None
    if not no_instructions:
        skill_dir = _write_codex_skill(_codex_jsat_skill_dir())
    action = "Updated" if already else "Added"
    console.print(f"\n[green]✓[/] {action} JSAT in Codex config: [cyan]{config_path}[/]")
    if skill_dir is not None:
        console.print(f"[green]✓[/] Installed Codex skill: [cyan]{skill_dir / 'SKILL.md'}[/]")
    console.print(
        "[dim]No project AGENTS.md, .agents/skills, or .codex files were generated.[/dim]\n"
        "[dim]Use `$jsat magic TASK` in Codex; `@jsat magic TASK` is treated as "
        "the same dispatcher request.[/dim]\n"
        "[dim]Run Codex from the target repo, or launch it with `jsat codex --repo PATH`.[/dim]\n"
    )
    console.print("[bold yellow]→ Restart Codex[/] to activate MCP and skill changes.\n")


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

    settings = _read_json_or_abort(config_path)
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
        proj_settings = _read_json_or_abort(zed_proj)
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
    _persist_ai_provider_if_default(
        Path.home() / ".jsat" / "config.yaml" if effective_scope == "global"
        else Path(repo_path) / ".jsat" / "config.yaml",
        "bob_cli",
    )

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
    ("Codex",                 Path.home() / ".codex" / "config.toml",    "mcpServers"),
    ("OpenCode",              _opencode_config_path(),                     "mcp"),
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
        if label.startswith("Codex"):
            if _has_toml_mcp_server(path, "jsat"):
                found_any = True
                console.print(f"[green]✓[/] [bold]{label}[/]  ({path})")
                console.print("   command: see [mcp_servers.jsat] in config.toml\n")
            continue
        try:
            data = _read_json(path)
        except ConfigParseError:
            console.print(f"[yellow]⚠[/] [bold]{label}[/]  ({path}) — invalid JSON, skipped")
            continue
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
    try:
        zed_cfg = _read_json(zed_path).get("context_servers", {}).get("jsat")
    except ConfigParseError:
        zed_cfg = None
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
            "  [bold]jsat connect opencode[/]   ← OpenCode / Ollama launch\n"
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

    settings = _read_json_or_abort(settings_path)
    if "jsat" in settings.get("mcpServers", {}):
        del settings["mcpServers"]["jsat"]
        _write_json(settings_path, settings)
        console.print(f"[green]✓[/] Removed JSAT from [bold]{settings_path}[/]")
    else:
        console.print(f"[dim]JSAT not found in {settings_path}[/]")
