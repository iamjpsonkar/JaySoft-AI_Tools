"""Top-level lifecycle commands for JSAT-managed AI clients."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import typer

from ._cli_common import app, console, err


def _validate_tool(tool: str) -> str:
    from jsat._lifecycle import MANAGED_TOOLS

    normalized = tool.strip().lower()
    if normalized not in MANAGED_TOOLS:
        choices = " | ".join(MANAGED_TOOLS)
        raise ValueError(f"choose a managed AI client: {choices}")
    return normalized


def _resolve_tool(tool: str, *, running_only: bool = False) -> str:
    from jsat._lifecycle import latest_record

    if tool.strip():
        return _validate_tool(tool)
    record = latest_record(running_only=running_only)
    if record is None:
        raise ValueError("no previous managed client; specify claude, codex, or opencode")
    return record.tool


def _is_all(tool: str) -> bool:
    return tool.strip().lower() in ("", "all")


def _terminal_command(command: list[str]) -> list[str] | None:
    """Wrap a command for a new terminal without invoking a shell."""
    candidates = (
        ("x-terminal-emulator", "-e"),
        ("gnome-terminal", "--"),
        ("konsole", "-e"),
        ("xfce4-terminal", "-x"),
    )
    for binary, separator in candidates:
        if path := shutil.which(binary):
            return [path, separator, *command]
    return None


def _fanout(action: str, tools: list[str], arguments: list[str]) -> None:
    """Open each interactive client in its own terminal window."""
    from ._cli_common import _jsat_binary

    for tool in tools:
        command = [_jsat_binary(), action, tool, *arguments]
        terminal = _terminal_command(command)
        if terminal is None:
            raise ValueError(
                "starting multiple interactive clients requires x-terminal-emulator, "
                "gnome-terminal, konsole, or xfce4-terminal; specify one TOOL instead"
            )
        subprocess.Popen(terminal)
        console.print(f"[green]✓[/] Opened [bold]{tool}[/] in a new terminal.")


def _native_binary(tool: str) -> str | None:
    if tool == "opencode":
        from jsat._ai.opencode_cli import _find_opencode

        return _find_opencode()
    return shutil.which(tool)


def _resolve_via(tool: str, via: str, previous=None) -> str:
    normalized = via.strip().lower()
    if normalized not in ("auto", "native", "ollama"):
        raise ValueError("--via must be auto, native, or ollama")
    if normalized != "auto":
        return normalized
    if previous is not None:
        return previous.via
    # Ollama installs OpenCode under ~/.opencode/bin as an implementation detail.
    # Treat only a PATH-visible OpenCode as an unambiguous native preference.
    if tool == "opencode" and not shutil.which("opencode") and shutil.which("ollama"):
        return "ollama"
    if _native_binary(tool):
        return "native"
    if shutil.which("ollama"):
        return "ollama"
    return "native"


def _via_with_model(via: str, model: str | None) -> str:
    """An explicit Ollama model makes the otherwise-auto route unambiguous."""
    return "ollama" if model and via.strip().lower() == "auto" else via


def _resume_args(tool: str, session: str | None) -> list[str]:
    if tool == "claude":
        return ["--resume", session] if session else ["--continue"]
    if tool == "codex":
        return ["resume", session] if session else ["resume", "--last"]
    return ["--session", session] if session else ["--continue"]


def _build_launch_command(
    tool: str,
    *,
    via: str,
    model: str | None,
    resume: bool = False,
    session: str | None = None,
    extra_args: list[str] | None = None,
) -> list[str]:
    trailing = _resume_args(tool, session) if resume else list(extra_args or [])
    if via == "ollama":
        ollama = shutil.which("ollama")
        if not ollama:
            raise ValueError("ollama not found in PATH")
        from jsat._ollama import build_ollama_launch_args

        return [ollama, *build_ollama_launch_args(tool, model=model, passthrough=trailing)]

    binary = _native_binary(tool)
    if not binary:
        raise ValueError(
            f"{tool} not found; install it or use --via ollama"
        )
    return [binary, *trailing]


def _ensure_connected(tool: str, repo: str) -> None:
    if tool == "claude":
        from jsat._cli_connect import cmd_connect_claude

        cmd_connect_claude(
            scope="global",
            global_=True,
            repo=repo,
            install_skills=True,
            show=False,
            write_claude_md=False,
        )
        return
    from jsat._cli_launchers import _auto_connect

    _auto_connect(tool, repo)


def _launch(
    tool: str,
    *,
    via: str,
    repo: str,
    model: str | None,
    resume: bool = False,
    session: str | None = None,
    extra_args: list[str] | None = None,
) -> int:
    from jsat._lifecycle import LifecycleRecord, run_foreground

    repo_abs = str(Path(repo).resolve())
    _ensure_connected(tool, repo_abs)
    command = _build_launch_command(
        tool,
        via=via,
        model=model,
        resume=resume,
        session=session,
        extra_args=extra_args,
    )
    action = "Resuming" if resume else "Starting"
    model_note = f" / {model}" if model else ""
    console.print(
        f"[green]✓[/] {action} [bold]{tool}[/] via [bold]{via}{model_note}[/]\n"
        f"[dim]  repo: {repo_abs}[/dim]"
    )
    return run_foreground(
        command,
        LifecycleRecord(tool=tool, via=via, repo=repo_abs, model=model),
    )


@app.command(
    "start",
    rich_help_panel="🤖  AI Launchers",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def cmd_start(
    ctx: typer.Context,
    tool: str = typer.Argument("all", help="claude | codex | opencode | all"),
    via: str = typer.Option("auto", "--via", help="auto | native | ollama"),
    model: str | None = typer.Option(None, "--model", "-m", help="Ollama model"),
    repo: str = typer.Option(".", "--repo", "-r", help="Repository root"),
) -> None:
    """Start and track an AI client with JSAT connected."""
    try:
        if _is_all(tool):
            from jsat._lifecycle import MANAGED_TOOLS

            chosen_via = _via_with_model(via, model)
            arguments = ["--via", chosen_via, "--repo", str(Path(repo).resolve())]
            if model:
                arguments += ["--model", model]
            if ctx.args:
                arguments += ["--", *ctx.args]
            _fanout("start", list(MANAGED_TOOLS), arguments)
            return
        selected = _resolve_tool(tool)
        route = _resolve_via(selected, _via_with_model(via, model))
        if model and route != "ollama":
            raise ValueError("--model is used only with --via ollama")
        code = _launch(
            selected,
            via=route,
            repo=repo,
            model=model,
            extra_args=list(ctx.args),
        )
    except ValueError as exc:
        err.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    if code:
        raise typer.Exit(code)


@app.command("stop", rich_help_panel="🤖  AI Launchers")
def cmd_stop(
    tool: str = typer.Argument("all", help="Managed client or all (default)"),
    force: bool = typer.Option(False, "--force", help="Send SIGKILL after the graceful timeout"),
) -> None:
    """Stop a validated process previously started by JSAT."""
    from jsat._lifecycle import is_running, load_record, stop_record

    if _is_all(tool):
        from jsat._lifecycle import list_records

        running = [record for record in list_records() if is_running(record)]
        stopped: list[str] = []
        failed: list[str] = []
        for record in running:
            target = stopped if stop_record(record, force=force) else failed
            target.append(record.tool)
        if not stopped:
            err.print("[yellow]No JSAT-managed clients are running.[/]")
            raise typer.Exit(1)
        console.print(f"[green]✓[/] Stopped [bold]{', '.join(stopped)}[/].")
        if failed:
            err.print(
                f"[yellow]Could not stop {', '.join(failed)}; retry with --force.[/]"
            )
            raise typer.Exit(1)
        return
    try:
        selected = _resolve_tool(tool)
    except ValueError as exc:
        err.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    record = load_record(selected)
    if record is None or not stop_record(record, force=force):
        err.print(
            f"[yellow]{selected} is not running as a JSAT-managed process.[/]\n"
            f"Start it once with: [bold]jsat start {selected}[/]"
        )
        raise typer.Exit(1)
    console.print(f"[green]✓[/] Stopped [bold]{selected}[/].")


@app.command(
    "restart",
    rich_help_panel="🤖  AI Launchers",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def cmd_restart(
    ctx: typer.Context,
    tool: str = typer.Argument("all", help="Managed client or all (default)"),
    via: str = typer.Option("auto", "--via", help="auto | native | ollama"),
    model: str | None = typer.Option(None, "--model", "-m"),
    repo: str | None = typer.Option(None, "--repo", "-r"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Stop a managed client if running, then start it with its previous route."""
    from jsat._lifecycle import is_running, load_record, stop_record

    try:
        if _is_all(tool):
            from jsat._lifecycle import MANAGED_TOOLS, list_records

            records = list_records()
            if not records:
                console.print(
                    "[yellow]No managed clients were recorded; launching all. "
                    "Existing unmanaged processes are left untouched.[/]"
                )
            arguments = ["--via", _via_with_model(via, model)]
            if model:
                arguments += ["--model", model]
            if repo:
                arguments += ["--repo", str(Path(repo).resolve())]
            if force:
                arguments.append("--force")
            if ctx.args:
                arguments += ["--", *ctx.args]
            _fanout("restart", list(MANAGED_TOOLS), arguments)
            return
        selected = _resolve_tool(tool)
        previous = load_record(selected)
        if previous is not None and is_running(previous) and not stop_record(
            previous, force=force
        ):
            raise ValueError(f"could not stop {selected}; retry with --force")
        route = _resolve_via(selected, _via_with_model(via, model), previous)
        chosen_model = model if model is not None else (previous.model if previous else None)
        chosen_repo = repo or (previous.repo if previous else ".")
        code = _launch(
            selected,
            via=route,
            repo=chosen_repo,
            model=chosen_model,
            extra_args=list(ctx.args),
        )
    except ValueError as exc:
        err.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    if code:
        raise typer.Exit(code)


@app.command("resume", rich_help_panel="🤖  AI Launchers")
def cmd_resume(
    tool: str = typer.Argument("all", help="Managed client or all (default)"),
    session: str | None = typer.Option(None, "--session", "-s", help="Specific session ID"),
    via: str = typer.Option("auto", "--via", help="auto | native | ollama"),
    model: str | None = typer.Option(None, "--model", "-m"),
    repo: str | None = typer.Option(None, "--repo", "-r"),
) -> None:
    """Resume the latest or a named AI-client session."""
    from jsat._lifecycle import load_record

    try:
        if _is_all(tool):
            from jsat._lifecycle import MANAGED_TOOLS

            targets = list(MANAGED_TOOLS)
            if session:
                raise ValueError("--session requires one explicit client")
            arguments = ["--via", _via_with_model(via, model)]
            if model:
                arguments += ["--model", model]
            if repo:
                arguments += ["--repo", str(Path(repo).resolve())]
            _fanout("resume", targets, arguments)
            return
        selected = _resolve_tool(tool)
        previous = load_record(selected)
        route = _resolve_via(selected, _via_with_model(via, model), previous)
        chosen_model = model if model is not None else (previous.model if previous else None)
        chosen_repo = repo or (previous.repo if previous else ".")
        code = _launch(
            selected,
            via=route,
            repo=chosen_repo,
            model=chosen_model,
            resume=True,
            session=session,
        )
    except ValueError as exc:
        err.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    if code:
        raise typer.Exit(code)


@app.command("ps", rich_help_panel="🤖  AI Launchers")
def cmd_ps() -> None:
    """List AI clients started and tracked by JSAT."""
    from rich import box
    from rich.table import Table

    from jsat._lifecycle import is_running, list_records

    records = list_records()
    if not records:
        console.print("[dim]No managed AI clients yet. Run `jsat start TOOL`.[/]")
        return
    table = Table(title="JSAT-managed AI clients", box=box.SIMPLE)
    for name in ("tool", "state", "pid", "via", "model", "repo"):
        table.add_column(name)
    for record in records:
        running = is_running(record)
        state = "[green]running[/]" if running else record.status
        table.add_row(
            record.tool,
            state,
            str(record.pid or "—"),
            record.via,
            record.model or "—",
            record.repo,
        )
    console.print(table)
