"""
jsat._cli_ai — AI provider management (jsat ai status/use/test/models).
"""
from __future__ import annotations

from pathlib import Path

import structlog
import typer
from rich import box
from rich.table import Table

from ._cli_common import _jsat, ai_app, console, err

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
            from jsat._ollama import ollama_model_kind
            models = [m["name"] for m in r.json().get("models", [])]
            local_count = sum(ollama_model_kind(m) == "local" for m in models)
            cloud_count = len(models) - local_count
            providers.append({
                "name": "ollama", "status": "running",
                "models": models, "free": bool(local_count) or not models,
                "hint": (
                    f"ollama serve  ({local_count} local, {cloud_count} cloud; "
                    f"models: {', '.join(models[:3]) or 'none registered yet'})"
                ),
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
        "free": False, "models": [],
        "hint": "set ANTHROPIC_API_KEY" if not key else "ready",
    })

    # OpenAI
    key = os.environ.get("OPENAI_API_KEY", "")
    providers.append({
        "name": "openai", "status": "key_set" if key else "no_key",
        "free": False, "models": [],
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
        current, current_model = "none", None

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
        f"\nCurrently configured: [bold]{current}[/] / "
        f"[bold]{current_model or 'automatic/not selected'}[/]\n"
        "Run [bold]jsat ai use <provider>[/] to switch.\n"
    )


def _preflight_ollama(model: str) -> bool:
    """Validate that Ollama is reachable and has registered the chosen model."""
    from jsat._ollama import ollama_model_kind, ollama_models_match

    kind = ollama_model_kind(model)
    if kind == "cloud":
        console.print(
            "[cyan]Cloud model selected.[/] Ollama will run inference remotely.\n"
            "  Sign in if needed: [bold]ollama signin[/]\n"
        )
    try:
        import httpx
        resp = httpx.get("http://localhost:11434/api/tags", timeout=1.0)
        resp.raise_for_status()
        installed = [m.get("name", "") for m in resp.json().get("models", [])]
    except Exception:
        console.print(
            "[yellow]⚠[/] Ollama is not running.\n"
            "  Start it:   [bold]ollama serve[/]\n"
            f"  Pull model: [bold]ollama pull {model}[/]\n"
        )
        return False

    if not any(ollama_models_match(m, model) for m in installed):
        action = "Sign in:     ollama signin" if kind == "cloud" else (
            f"Pull it:     ollama pull {model}"
        )
        installed_note = ", ".join(installed[:5]) or "none"
        console.print(
            f"[yellow]⚠[/] Model [bold]{model}[/] is not registered with this Ollama host.\n"
            f"  Installed:  {installed_note}\n"
            f"  {action}\n"
            "  Discover:    [bold]jsat ai models ollama[/]\n"
        )
        if installed:
            console.print(
                f"  Or use:     [bold]jsat ai use ollama --model {installed[0]}[/]\n"
            )
        return False
    return True


@ai_app.command("use")
def cmd_ai_use(
    provider: str = typer.Argument(...,
        help=(
            "Provider: ollama | anthropic | openai | lmstudio | claude_cli | "
            "codex_cli | opencode_cli | bob_cli"
        )),
    model: str | None = typer.Option(None, "--model", "-m",
        help="Explicit model; native CLIs use their own default when omitted"),
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
      jsat ai models ollama                    # discover installed/registered models
      jsat ai use ollama --model <model>
      jsat ai use anthropic --model <model>    # needs ANTHROPIC_API_KEY
      jsat ai use openai --model <model>       # needs OPENAI_API_KEY
      jsat ai use lmstudio --model <model>     # LM Studio at localhost:1234
      jsat ai use claude_cli --global          # Claude Code CLI, global config
      jsat ai use opencode --global            # OpenCode's configured model
    """
    import os

    from jsat._ai.aliases import MCP_TOOLS, alias_names, normalize_alias, resolve_alias, suggest

    # Same alias table the SDK and shell use, so every documented name works here.
    resolved = resolve_alias(provider)
    if resolved is None:
        lines = [f"[red]Unknown provider:[/] {provider!r}"]
        # An MCP tool name is a category mistake, not a typo — check it before fuzzy matching.
        if normalize_alias(provider) in MCP_TOOLS:
            lines.append(
                f"[bold]{provider}[/] is an editor/CLI, not an AI provider — "
                f"use [bold]jsat connect {provider}[/] instead."
            )
        else:
            close = suggest(provider, alias_names())
            if close:
                lines.append(f"Did you mean [bold]{close[0]}[/]?")
        lines.append("Valid: " + " | ".join(alias_names()))
        err.print("\n".join(lines))
        raise typer.Exit(1)

    chosen_provider, default_model, base_url, resolved_api_key_env = resolved
    chosen_model = model if model is not None else default_model

    cli_providers = {"claude_cli", "codex_cli", "opencode_cli", "bob_cli"}
    if (
        chosen_provider == "ollama"
        and normalize_alias(provider) in {"phi", "llama"}
        and chosen_model is None
    ):
        err.print(
            f"[yellow]Alias '{provider}' identifies a model family, not a model.[/]\n"
            "  Discover: [bold]jsat ai models ollama[/]\n"
            f"  Select:   [bold]jsat ai use {provider} --model <model>[/]"
        )
        raise typer.Exit(1)
    if chosen_provider == "ollama" and chosen_model is None:
        from jsat._ollama import select_ollama_model

        available: list[str] = []
        try:
            import httpx

            response = httpx.get("http://localhost:11434/api/tags", timeout=1.0)
            response.raise_for_status()
            available = [m["name"] for m in response.json().get("models", [])]
        except Exception:
            pass
        try:
            chosen_model = select_ollama_model(None, available)
        except ValueError as exc:
            err.print(f"[yellow]{exc}[/]")
            raise typer.Exit(1) from exc

    if chosen_provider not in cli_providers | {"ollama"} and chosen_model is None:
        err.print(
            f"[yellow]Provider '{chosen_provider}' needs an explicit model.[/]\n"
            f"  Discover: [bold]jsat ai models {provider}[/]\n"
            f"  Select:   [bold]jsat ai use {provider} --model <model>[/]"
        )
        raise typer.Exit(1)

    # Pre-flight checks — keyed on the resolved backend, not the alias the user typed
    if chosen_provider == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY"):
        console.print("[yellow]⚠[/] ANTHROPIC_API_KEY is not set.")
        console.print("  Add to your shell: [bold]export ANTHROPIC_API_KEY=sk-ant-...[/]\n")

    if chosen_provider == "openai" and not os.environ.get("OPENAI_API_KEY"):
        console.print("[yellow]⚠[/] OPENAI_API_KEY is not set.")
        console.print("  Add to your shell: [bold]export OPENAI_API_KEY=sk-...[/]\n")

    if resolved_api_key_env and not os.environ.get(resolved_api_key_env):
        console.print(f"[yellow]⚠[/] {resolved_api_key_env} is not set.")
        console.print(f"  Add to your shell: [bold]export {resolved_api_key_env}=...[/]\n")

    for binary, install_hint in (
        ("claude_cli", "claude"),
        ("opencode_cli", "opencode"),
        ("bob_cli", "bob"),
    ):
        if chosen_provider == binary:
            import shutil
            if not shutil.which(install_hint):
                console.print(
                    f"[yellow]⚠[/] The [bold]{install_hint}[/] binary was not found on PATH.\n"
                    f"  Install it, or pick another provider with [bold]jsat ai status[/].\n"
                )

    if (
        chosen_provider == "ollama"
        and chosen_model is not None
        and not _preflight_ollama(chosen_model)
    ):
        raise typer.Exit(1)

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
    previous_provider = existing["ai"].get("provider")
    existing["ai"]["provider"] = chosen_provider
    if chosen_model is None:
        existing["ai"].pop("model", None)
    else:
        existing["ai"]["model"] = chosen_model
    if previous_provider != chosen_provider:
        existing["ai"].pop("base_url", None)
        existing["ai"].pop("api_key_env", None)
    if base_url:
        existing["ai"]["base_url"] = base_url
    if resolved_api_key_env:
        existing["ai"]["api_key_env"] = resolved_api_key_env

    # Write back
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with cfg_path.open("w") as f:
        yaml.dump(existing, f, default_flow_style=False, sort_keys=False)

    scope_label = "global" if global_ else "project"
    model_label = chosen_model or "provider default"
    console.print(
        f"\n[green]✓[/] AI provider set: [bold]{chosen_provider}[/] / [bold]{model_label}[/]"
        f"  [{scope_label}]"
    )
    console.print(f"   Written to: [cyan]{cfg_path.resolve()}[/]\n")

    # Quick connectivity test
    console.print("[dim]Testing connection...[/]", end=" ")
    try:
        from jsat._core import JSAT
        js = JSAT(repo=".", config=cfg_path, log_level="ERROR")
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
def cmd_ai_models(
    requested_provider: str | None = typer.Argument(
        None, metavar="[PROVIDER]", help="Provider to inspect; default: configured provider"
    ),
) -> None:
    """Discover models or show how the selected client chooses one."""
    try:

        import httpx
        js = _jsat()
        provider = js._cfg.ai.provider
        if requested_provider:
            from jsat._ai.aliases import resolve_alias

            resolved = resolve_alias(requested_provider)
            if resolved is None:
                raise ValueError(f"unknown provider: {requested_provider}")
            provider = resolved[0]

        if provider == "ollama":
            from jsat._ollama import ollama_model_kind
            r = httpx.get("http://localhost:11434/api/tags", timeout=2.0)
            r.raise_for_status()
            models = [m["name"] for m in r.json().get("models", [])]
            if not models:
                console.print(
                    "[yellow]No Ollama models are registered.[/]\n"
                    "  Browse: [bold]ollama[/] (interactive model selector)\n"
                    "  Local:  [bold]ollama pull <model>[/]\n"
                    "  Cloud:  [bold]ollama signin[/]\n"
                )
                return
            console.print(f"\n[bold]Ollama models ({len(models)}):[/]")
            for m in models:
                active = " [cyan]← active[/]" if m == js._cfg.ai.model else ""
                kind = ollama_model_kind(m)
                style = "magenta" if kind == "cloud" else "green"
                console.print(f"  {m} [{style}]{kind}[/]{active}")

        elif provider == "openai_compat":
            base = js._cfg.ai.base_url or "http://localhost:1234/v1"
            r = httpx.get(f"{base}/models", timeout=2.0)
            r.raise_for_status()
            models = [m["id"] for m in r.json().get("data", [])]
            console.print(f"\n[bold]Models at {base} ({len(models)}):[/]")
            for m in models:
                console.print(f"  {m}")

        elif provider in {"claude_cli", "codex_cli", "opencode_cli", "bob_cli"}:
            commands = {
                "claude_cli": "Open Claude Code and use /model; omit --model to use its default.",
                "codex_cli": "Open Codex and use its model selector; `codex --help` shows flags.",
                "opencode_cli": "Open OpenCode and use its model/provider selector.",
                "bob_cli": "Open Bob Shell and use its configured model/mode selector.",
            }
            console.print(
                f"[bold]{provider} owns model selection.[/]\n{commands[provider]}\n"
                f"To pin one explicitly: [bold]jsat ai use {requested_provider or provider} "
                "--model <model>[/]"
            )
        elif provider in {"openai", "anthropic"}:
            console.print(
                f"[bold]{provider} model discovery uses your account credentials.[/]\n"
                f"Set the provider API key, then consult its model list or run its SDK's "
                "models-list operation.\n"
                f"Select one with: [bold]jsat ai use {requested_provider or provider} "
                "--model <model>[/]"
            )
        else:
            console.print(
                f"[dim]Provider '{provider}' does not expose a local model list.[/]\n"
                f"Current model: [bold]{js._cfg.ai.model or 'not selected'}[/]"
            )
    except Exception as e:
        err.print(f"[red]Could not list models:[/] {e}")
        raise typer.Exit(1) from e
