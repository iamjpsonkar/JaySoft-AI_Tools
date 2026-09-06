"""jsat._cli_ui — the Studio: `jsat ui` web app and `jsat ui --tui` terminal UI."""
from __future__ import annotations

import signal
import threading

import structlog
import typer

from ._cli_common import _jsat, app, console, err

_log = structlog.get_logger(__name__)


@app.command("ui", rich_help_panel="🎨  Studio")
def cmd_ui(
    port: int = typer.Option(7433, "--port", "-p", help="Port for the Studio web server"),
    no_open: bool = typer.Option(False, "--no-open", help="Do not open a browser tab"),
    tui: bool = typer.Option(False, "--tui", help="Run the terminal UI instead of the web app"),
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address (keep localhost!)"),
    repo: str = typer.Argument(".", help="Repository to load"),
) -> None:
    """Open the JSAT Studio — a full UI over every JSAT surface.

    \b
    jsat ui            ← web app (stdlib-only, opens a browser tab)
    jsat ui --tui      ← terminal UI (needs `pip install 'jsat[studio]'`)
    jsat ui --no-open  ← start the server without opening the browser
    """
    js = _jsat(repo=repo)
    if tui:
        from jsat.ui.tui import run_tui

        raise typer.Exit(run_tui(js, port=port + 1))

    from jsat.ui.server import start_studio

    url, _ = start_studio(js, port=port, host=host, open_browser=not no_open)
    if url is None:
        err.print(f"[red]Cannot bind Studio server on {host}:{port}[/red] "
                  f"([dim]is another instance running?[/dim])")
        raise typer.Exit(1)
    console.print(f"[cyan]JSAT Studio[/cyan] → [bold]{url}[/bold] "
                  f"([dim]Ctrl+C to stop[/dim])")

    stop = threading.Event()
    def _sig(_signum: object, _frame: object) -> None:
        stop.set()
    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)
    try:
        while not stop.wait(1.0):
            if not threading.enumerate():
                break
    except KeyboardInterrupt:
        pass
    finally:
        console.print("\n[dim]Studio stopped.[/dim]")