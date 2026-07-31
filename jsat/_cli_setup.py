"""
jsat._cli_setup — Setup, config, and package commands.
"""
from __future__ import annotations

import contextlib
from pathlib import Path

import structlog
import typer

from ._cli_common import app, skills_app, console, err, _jsat, _jsat_binary, _read_json, _write_json
from ._cli_connect import _remove_jsat_block

_log = structlog.get_logger(__name__)

# ── disconnect ─────────────────────────────────────────────────────────────────

@app.command("disconnect", rich_help_panel="🔧  Setup & Config")
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
                removed: list[Path] = list(cd.glob("jsat-*.md"))
                for f in removed:
                    f.unlink()
                # Also remove the dispatcher (jsat.md doesn't match jsat-*.md glob)
                dispatcher = cd / "jsat.md"
                if dispatcher.exists():
                    dispatcher.unlink()
                    removed.append(dispatcher)
                if removed:
                    console.print(
                        f"[green]✓[/] Removed {len(removed)} JSAT skill file(s) from [bold]{cd}[/]"
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

# ── version ──────────────────────────────────────────────────────────────────

@app.command("version", rich_help_panel="📦  Package")
def cmd_version() -> None:
    """Print JSAT version and build info.

    \b
    Examples:
      jsat version
    """
    from jsat import __version__
    console.print(f"jsat {__version__}")


# ── init ──────────────────────────────────────────────────────────────────────

@app.command("init", rich_help_panel="🔧  Setup & Config")
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

# ── ci-setup ──────────────────────────────────────────────────────────────────

@app.command("ci-setup", rich_help_panel="🔧  Setup & Config")
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

@app.command("mcp-server", rich_help_panel="🔧  Setup & Config")
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

# ── update ─────────────────────────────────────────────────────────────────────

@app.command("update", rich_help_panel="📦  Package")
def cmd_update(
    pre: bool = typer.Option(False, "--pre", help="Include pre-release versions"),
) -> None:
    """Upgrade JSAT to the latest version from PyPI.

    Equivalent to: pip install --upgrade jsat

    \b
    Examples:
      jsat update
    """
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
