"""
jsat._cli_ai — AI provider management (jsat ai status/use/test/models).
"""
from __future__ import annotations

from pathlib import Path

import structlog
import typer
from rich import box
from rich.table import Table

from ._cli_common import ai_app, console, err, _jsat

_log = structlog.get_logger(__name__)

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
