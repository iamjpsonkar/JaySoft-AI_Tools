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
from typer.core import TyperGroup

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
def _usage_errors() -> tuple[type[BaseException], ...]:
    """Both UsageError classes: the real click one and typer's vendored copy.

    Typer >=0.27 ships `typer._click`, whose `UsageError` is a *different class*
    from `click.UsageError`. Catching only one silently misses the other depending
    on which path invoked the command, so catch whichever exist.
    """
    import click
    errors: list[type[BaseException]] = [click.exceptions.UsageError]
    try:
        from typer._click.exceptions import UsageError as _VendoredUsageError
        if _VendoredUsageError not in errors:
            errors.append(_VendoredUsageError)
    except Exception:
        pass
    return tuple(errors)


class ConnectGroup(TyperGroup):
    """Turns `jsat connect <unknown>` into an actionable error.

    AI-provider names that are not also connection targets are redirected to
    ``jsat ai use``. Some names intentionally exist in both namespaces.
    """

    def resolve_command(self, ctx, args):  # type: ignore[no-untyped-def]
        try:
            return super().resolve_command(ctx, args)
        except _usage_errors():
            name = args[0] if args else ""
            from jsat._ai.aliases import MCP_TOOLS, is_provider_alias, suggest
            registered = list(self.list_commands(ctx))
            # Only the tool subcommands are useful here — hide `list`/`remove`.
            valid = [c for c in registered if c in MCP_TOOLS] or registered

            was_provider = is_provider_alias(name)
            # Record the SHAPE of the mistake only — `name` is user input and is
            # never stored.
            try:
                from jsat._improve import record_signal
                record_signal(
                    kind="ux_friction", source="cli", op="connect",
                    detail={"reason": "unknown_target",
                            "was_provider_alias": was_provider},
                )
            except Exception:
                pass

            err.print(f"[red]Unknown connect target:[/] {name!r}")
            if was_provider:
                err.print(
                    f"[bold]{name}[/] is an AI provider, not an MCP tool — "
                    f"configure it with:\n  [bold]jsat ai use {name}[/]"
                )
            else:
                close = suggest(name, valid)
                if close:
                    err.print(f"Did you mean [bold]jsat connect {close[0]}[/]?")
            err.print("Connectable tools: " + " | ".join(valid))
            raise typer.Exit(1) from None


connect_app = typer.Typer(
    cls=ConnectGroup,
    help=(
        "Wire JSAT into AI tools as an MCP server.\n\n"
        "[bold]One-time global setup (recommended):[/bold]\n\n"
        "  [cyan]jsat connect claude --global[/cyan]   — all Claude Code sessions\n"
        "  [cyan]jsat connect codex[/cyan]             — Codex CLI\n"
        "  [cyan]jsat connect opencode[/cyan]          — OpenCode (including Ollama launch)\n"
        "  [cyan]jsat connect ollama[/cyan]            — all supported Ollama-launched tools\n"
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
        try:
            from jsat._improve import record_signal
            record_signal(kind="crash", source="cli", exc=e, op="init")
        except Exception:
            pass
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


class ConfigParseError(Exception):
    """Raised when an existing config file exists but fails to parse as JSON.

    Callers that are about to overwrite ``path`` via ``_write_json`` MUST catch
    this and refuse to proceed — silently swallowing it and writing anyway would
    destroy the user's existing (merely malformed) settings.
    """

    def __init__(self, path: Path, original: Exception) -> None:
        self.path = path
        self.original = original
        super().__init__(
            f"{path} exists but is not valid JSON ({original}). "
            "Fix the file manually (or remove it) before retrying — refusing to "
            "overwrite it automatically."
        )


def _read_json(path: Path) -> dict:
    """Read JSON file; return {} if missing.

    Raises ``ConfigParseError`` if the file exists but is not valid JSON, so
    callers that would otherwise call ``_write_json`` on the same path can abort
    instead of silently clobbering the user's existing config.
    """
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigParseError(path, e) from e


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _read_json_or_abort(path: Path) -> dict:
    """Like ``_read_json``, but prints a clear error and exits instead of raising.

    Use this at any call site that is about to merge new keys into ``path`` and
    then call ``_write_json`` on it — malformed-but-recoverable JSON must never
    be silently replaced with a file containing only the newly written keys.
    """
    try:
        return _read_json(path)
    except ConfigParseError as e:
        err.print(f"[bold red]✗[/] {e}")
        raise typer.Exit(1) from e
