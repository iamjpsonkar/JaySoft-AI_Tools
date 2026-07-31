"""
jsat._cli_common — Typer app objects and shared CLI utilities.

Imported by all other _cli_* modules.
"""
from __future__ import annotations

import json
from pathlib import Path

import structlog
import typer
from rich.console import Console

_log = structlog.get_logger(__name__)

app = typer.Typer(
    name="jsat",
    help=(
        "[bold]JSAT[/bold] — Codebase intelligence for AI sessions.\n\n"
        "Index your codebase once, then query, analyze, and reason over it "
        "from any AI tool — Claude Code, Cursor, Codex, Gemini, and more.\n\n"
        "\b\n"
        "Quick start:\n"
        "  jsat index .                  — build the graph\n"
        "  jsat connect claude --global  — wire into Claude Code\n"
        "  jsat doctor                   — verify everything works\n\n"
        "\b\n"
        "Then in Claude Code:\n"
        "  /jsat query    <question>   — answer any codebase question\n"
        "  /jsat crack    <task>       — multi-agent war room\n"
        "  /jsat blast    <file>       — trace impact of a change\n"
        "  /jsat security              — OWASP scan\n"
        "  /jsat aw       <task>       — full workflow advisor\n\n"
        "Docs: https://github.com/iamjpsonkar/JaySoft-AI_Tools"
    ),
    add_completion=True,
    no_args_is_help=True,
    rich_markup_mode="rich",
)
skills_app = typer.Typer(
    help=(
        "Manage and run JSAT skills.\n\n"
        "[bold]Commands:[/bold]\n\n"
        "  [cyan]jsat skills list[/cyan]          — list installed skill manifests\n"
        "  [cyan]jsat skills run <name>[/cyan]    — run a named skill"
    ),
    rich_markup_mode="rich",
)
connect_app = typer.Typer(
    help=(
        "Wire JSAT into AI tools as an MCP server.\n\n"
        "[bold]One-time global setup (recommended):[/bold]\n\n"
        "  [cyan]jsat connect claude --global[/cyan]   — all Claude Code sessions\n"
        "  [cyan]jsat connect codex  --global[/cyan]   — Codex CLI\n"
        "  [cyan]jsat connect cursor[/cyan]             — Cursor IDE\n\n"
        "Restart the AI tool after connecting."
    ),
    rich_markup_mode="rich",
)
app.add_typer(skills_app,  name="skills",  rich_help_panel="🔧  Setup & Config")
app.add_typer(connect_app, name="connect", rich_help_panel="🔧  Setup & Config")

ai_app = typer.Typer(
    help=(
        "Configure and test the AI provider JSAT uses.\n\n"
        "[bold]Quick setup:[/bold]\n\n"
        "  [cyan]jsat ai use claude_cli[/cyan]    — use Claude Code CLI (no key)\n"
        "  [cyan]jsat ai use ollama[/cyan]         — local Ollama (free)\n"
        "  [cyan]jsat ai use anthropic[/cyan]      — Anthropic API (ANTHROPIC_API_KEY)\n"
        "  [cyan]jsat ai status[/cyan]             — see all available providers\n"
        "  [cyan]jsat ai test[/cyan]               — verify the active provider works"
    ),
    rich_markup_mode="rich",
)
app.add_typer(ai_app, name="ai", rich_help_panel="🔧  Setup & Config")

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
