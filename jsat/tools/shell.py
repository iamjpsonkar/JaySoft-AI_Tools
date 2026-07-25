"""
jsat.tools.shell — Universal AI Shell.

Ask anything. Response from whichever AI is configured.
Switch AI mid-session with: switch claude | switch gpt | switch ollama | etc.

Launch: jsat shell
"""
from __future__ import annotations

import readline
import shlex
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from jsat._core import JSAT

# ── Command registry ──────────────────────────────────────────────────────────

_COMMANDS: dict[str, str] = {
    "switch":         "switch <ai> — switch AI  |  'switch claude-cli' opens full Claude + JSAT tools",
    "index":          "index [PATH] — build/update the codebase graph",
    "blast-radius":   "blast-radius <FILE> — trace downstream impact",
    "test-gaps":      "test-gaps [SERVICE] — find untested code paths",
    "feature":        "feature <DESC> — generate implementation plan",
    "contract-check": "contract-check [BASE] — validate API contract",
    "security-review":"security-review [PATH] — OWASP + secret scan",
    "incident":       "incident <DESC> — investigate a production incident",
    "migrate-check":  "migrate-check <FILE> — validate a migration file",
    "review":         "review [BASE] — multi-model code review",
    "knowledge":      "knowledge add|query|list <TEXT>",
    "export":         "export <OUTPUT> — export index as zip",
    "doctor":         "doctor — system health check",
    "status":         "status — index statistics",
    "ai":             "ai — show current AI provider",
    "help":           "help — show this message",
    "exit":           "exit / quit — leave the shell",
    "opt":            "opt on|off|show|history — toggle/inspect prompt optimizer",
}

_PROVIDERS = [
    "claude", "anthropic", "haiku", "opus",
    "gpt", "openai", "gpt4", "gpt4mini", "chatgpt", "codex",
    "ollama", "llama", "phi",
    "gemini", "gemini-pro",
    "lmstudio", "lm-studio",
    "custom", "compat",
]

_COMPLETIONS = sorted(list(_COMMANDS.keys()) + _PROVIDERS + ["quit"])


class JSATShell:
    """Universal AI shell backed by a JSAT instance."""

    def __init__(self, jsat: JSAT) -> None:
        import structlog
        from rich.console import Console

        self._js = jsat
        self._console = Console()
        self._log = structlog.get_logger(__name__)
        self._running = False
        self._prompt_opt: bool = True          # optimizer on by default
        self._last_optimized: str | None = None
        self._last_raw: str | None = None     # raw input before optimization
        self._setup_readline()

    # ── Readline setup ────────────────────────────────────────────────────────

    def _setup_readline(self) -> None:
        try:
            history_path = Path.home() / ".jsat_history"
            if history_path.exists():
                readline.read_history_file(str(history_path))
            readline.set_history_length(2000)

            def completer(text: str, state: int) -> str | None:
                options = [c for c in _COMPLETIONS if c.startswith(text.lower())]
                return options[state] if state < len(options) else None

            readline.set_completer(completer)
            readline.set_completer_delims(" \t")
            readline.parse_and_bind("tab: complete")
            self._history_path = history_path
        except Exception:
            self._history_path = None

    def _save_history(self) -> None:
        if self._history_path:
            try:
                readline.write_history_file(str(self._history_path))
            except Exception:
                pass

    # ── AI label ──────────────────────────────────────────────────────────────

    def _ai_label(self) -> str:
        try:
            return self._js.active_ai_label()
        except Exception:
            return "no AI"

    def _prompt(self) -> str:
        return f"jsat [{self._ai_label()}]> "

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self) -> None:
        from rich.panel import Panel

        # Banner
        ai = self._ai_label()
        status = self._js.index_status
        index_info = (
            f"{status.get('nodes', 0):,} nodes · {status.get('edges', 0):,} edges"
            if status.get("nodes", 0) > 0 else "no index — run: index ."
        )
        self._console.print(Panel(
            f"[bold cyan]JSAT Universal AI Shell[/]  v0.1.0\n"
            f"AI : [green]{ai}[/]\n"
            f"Repo: [dim]{self._js._repo}[/]\n"
            f"Index: [dim]{index_info}[/]\n\n"
            "[dim]Ask anything · Tab-complete · type [bold]help[/bold]\n"
            "[bold]switch claude-cli[/bold] → full Claude Code + JSAT tools (all features)[/dim]",
            border_style="cyan",
        ))

        self._running = True
        while self._running:
            try:
                raw = input(self._prompt()).strip()
            except (EOFError, KeyboardInterrupt):
                self._console.print("\n[dim]Goodbye.[/dim]")
                break

            if not raw:
                continue
            self._dispatch(raw)

        self._save_history()

    # ── Dispatch ──────────────────────────────────────────────────────────────

    def _dispatch(self, raw: str) -> None:
        try:
            parts = shlex.split(raw)
        except ValueError:
            parts = raw.split()

        cmd = parts[0].lower() if parts else ""
        args = parts[1:]

        handlers: dict[str, Callable] = {
            "help":           lambda _: self._help(),
            "exit":           lambda _: self._exit(),
            "quit":           lambda _: self._exit(),
            "switch":         self._cmd_switch,
            "ai":             lambda _: self._show_ai(),
            "opt":            self._cmd_opt,
            "index":          self._cmd_index,
            "blast-radius":   self._cmd_blast_radius,
            "test-gaps":      self._cmd_test_gaps,
            "feature":        self._cmd_feature,
            "contract-check": self._cmd_contract,
            "security-review":self._cmd_security,
            "incident":       self._cmd_incident,
            "migrate-check":  self._cmd_migrate,
            "review":         self._cmd_review,
            "knowledge":      self._cmd_knowledge,
            "export":         self._cmd_export,
            "doctor":         self._cmd_doctor,
            "status":         self._cmd_status,
        }

        if cmd in handlers:
            try:
                handlers[cmd](args)
            except Exception as e:
                self._console.print(f"[red]Error:[/] {e}")
        else:
            # Everything else → AI chat
            self._chat(raw)

    # ── AI switching ──────────────────────────────────────────────────────────

    # ── Key requirements per provider ────────────────────────────────────────

    _KEY_REQUIREMENTS: dict[str, tuple[str, str]] = {
        # alias → (env_var_name, display_name)
        "claude":     ("ANTHROPIC_API_KEY", "Anthropic API key"),
        "anthropic":  ("ANTHROPIC_API_KEY", "Anthropic API key"),
        "haiku":      ("ANTHROPIC_API_KEY", "Anthropic API key"),
        "opus":       ("ANTHROPIC_API_KEY", "Anthropic API key"),
        "gpt":        ("OPENAI_API_KEY",    "OpenAI API key"),
        "openai":     ("OPENAI_API_KEY",    "OpenAI API key"),
        "chatgpt":    ("OPENAI_API_KEY",    "OpenAI API key"),
        "gpt4":       ("OPENAI_API_KEY",    "OpenAI API key"),
        "gpt4mini":   ("OPENAI_API_KEY",    "OpenAI API key"),
        "codex":      ("OPENAI_API_KEY",    "OpenAI API key"),
        "gemini":     ("GEMINI_API_KEY",    "Gemini API key"),
        "gemini-pro": ("GEMINI_API_KEY",    "Gemini API key"),
    }

    def _ensure_key(self, provider: str) -> bool:
        """If provider needs an API key and it's missing, prompt for it inline.
        Returns True if the key is now available, False if the user skipped."""
        import getpass
        import os

        req = self._KEY_REQUIREMENTS.get(provider)
        if req is None:
            return True  # no key needed (ollama, lmstudio, etc.)

        env_var, display_name = req
        if os.environ.get(env_var):
            return True  # already set

        self._console.print(
            f"\n[yellow]→ {display_name} required.[/]\n"
            f"  Enter your key below (input hidden). "
            f"Press Enter to skip.\n"
        )
        try:
            key = getpass.getpass(f"  {env_var}: ").strip()
        except (KeyboardInterrupt, EOFError):
            key = ""

        if not key:
            self._console.print("[dim]  Skipped — provider may not work without a key.[/dim]")
            return False

        # Set for the current process (survives this session only)
        os.environ[env_var] = key

        # Offer to persist to shell profile
        self._console.print("\n  [green]✓ Key set for this session.[/]")
        try:
            save = input("  Save to ~/.zshrc / ~/.bashrc? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            save = "n"

        if save == "y":
            self._save_key_to_profile(env_var, key)

        return True

    def _save_key_to_profile(self, env_var: str, key: str) -> None:
        """Append export VAR=key to the user's shell profile."""
        import os
        shell = os.environ.get("SHELL", "")
        candidates = []
        if "zsh" in shell:
            candidates = [Path.home() / ".zshrc"]
        elif "bash" in shell:
            candidates = [Path.home() / ".bashrc", Path.home() / ".bash_profile"]
        else:
            candidates = [Path.home() / ".profile"]

        profile = next((p for p in candidates if p.exists()), candidates[0])
        line = f'\nexport {env_var}="{key}"  # added by jsat\n'
        try:
            with profile.open("a") as f:
                f.write(line)
            self._console.print(f"  [green]✓ Saved to {profile}[/]  (run: source {profile})")
        except Exception as e:
            self._console.print(f"  [red]Could not write to {profile}:[/] {e}")

    def _cmd_switch(self, args: list[str]) -> None:
        """switch <provider> [model]

        switch claude-cli  → opens the real Claude Code with ALL JSAT tools as MCP
        switch claude      → uses claude CLI for Q&A (session-based)
        switch gpt         → OpenAI GPT
        switch ollama      → local Ollama
        """
        if not args:
            self._console.print(
                "[yellow]Usage:[/] switch <provider> [model]\n"
                "  [cyan]switch claude-cli[/]  ← Full Claude Code + JSAT MCP tools (recommended)\n"
                "  switch claude | gpt | ollama | gemini | lmstudio | anthropic"
            )
            return

        provider = args[0].lower()

        # Special: launch full interactive Claude Code with JSAT as MCP tools
        if provider in ("claude-cli", "claude-interactive", "claude-full", "full"):
            self._launch_claude_with_jsat_tools()
            return

        model    = args[1] if len(args) > 1 else None
        base_url = args[2] if len(args) > 2 else None

        # Prompt for missing API key before attempting switch
        if not self._ensure_key(provider):
            self._console.print("[dim]  Continuing without key — switch will show unreachable.[/dim]\n")

        self._console.print(f"[dim]Switching to [bold]{provider}[/bold]...[/dim]", end=" ")
        try:
            _, chosen_model, ok = self._js.switch_ai(provider, model=model, base_url=base_url)
            label = self._ai_label()
            if ok:
                self._console.print(f"[green]✓ {label}[/]")
            else:
                self._console.print(
                    f"[yellow]⚠ {label} — still not reachable.[/]\n"
                    + self._provider_hint(provider)
                )
        except ValueError as e:
            self._console.print(f"\n[red]Error:[/] {e}")

    def _launch_claude_with_jsat_tools(self) -> None:
        """Launch the real Claude Code CLI with JSAT available as MCP tools.

        This gives you EVERYTHING the claude CLI has:
          ✓ Full multi-turn conversation with memory
          ✓ Claude can read/write files, run bash (all Claude tools)
          ✓ Claude slash commands (/help, /clear, /memory, etc.)
          ✓ JSAT tools available to Claude via MCP:
              query, blast_radius, security_review, investigate_incident,
              index_repo, get_index_status, export_index, get_jsat_version
          ✓ Type 'exit' or Ctrl+D to return to JSAT shell
        """
        import json
        import os
        import shutil
        import subprocess
        import tempfile

        if not shutil.which("claude"):
            self._console.print(
                "[red]claude CLI not found.[/]\n"
                "Install Claude Code: https://claude.ai/code"
            )
            return

        # Find jsat binary
        jsat_bin = shutil.which("jsat") or sys.argv[0]
        repo = str(self._js._repo)
        index_status = self._js.index_status
        nodes = index_status.get("nodes", 0)
        edges = index_status.get("edges", 0)

        # MCP config pointing to JSAT server
        mcp_config = {
            "mcpServers": {
                "jsat": {
                    "command": jsat_bin,
                    "args": ["mcp-server", "--repo", repo],
                    "env": {},
                }
            }
        }

        # System prompt telling Claude about JSAT tools
        jsat_context = (
            f"You are working in the codebase at: {repo}\n"
            f"JSAT graph: {nodes:,} nodes, {edges:,} edges indexed.\n\n"
            "JSAT MCP tools available to you:\n"
            "  jsat__query              — answer any codebase question using the graph\n"
            "  jsat__blast_radius       — trace downstream impact of any file/symbol change\n"
            "  jsat__security_review    — find OWASP issues and hardcoded secrets\n"
            "  jsat__investigate_incident — score recent commits as root-cause hypotheses\n"
            "  jsat__index_repo         — rebuild the codebase graph index\n"
            "  jsat__get_index_status   — check how many nodes/edges are indexed\n"
            "  jsat__export_index       — export the graph as a portable archive\n\n"
            "Use these tools proactively when answering questions about the codebase. "
            "You also have full access to the repo files via your built-in tools."
        )

        mcp_config_path = None
        try:
            # Write temp MCP config
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False, prefix="jsat-mcp-"
            ) as f:
                json.dump(mcp_config, f, indent=2)
                mcp_config_path = f.name

            self._console.print(
                f"\n[bold cyan]Opening Claude Code with JSAT tools[/bold cyan] 🚀\n"
                f"\n  Repo  : [cyan]{repo}[/cyan]"
                f"\n  Index : [cyan]{nodes:,} nodes · {edges:,} edges[/cyan]"
                f"\n  JSAT tools: [cyan]query · blast_radius · security_review · "
                f"investigate_incident · index_repo · ...[/cyan]"
                f"\n\n[dim]Type [bold]/help[/bold] inside Claude for commands. "
                f"[bold]exit[/bold] or Ctrl+D to return here.[/dim]\n"
            )

            # Launch claude in fully interactive mode with JSAT MCP + file access
            subprocess.run(
                [
                    "claude",
                    "--mcp-config", mcp_config_path,
                    "--add-dir", repo,
                    "--append-system-prompt", jsat_context,
                ],
                # No capture_output — fully interactive, inherits terminal
            )

        finally:
            if mcp_config_path:
                try:
                    os.unlink(mcp_config_path)
                except Exception:
                    pass

        self._console.print(
            "\n[dim]← Back in JSAT shell. "
            "Your Claude session history is preserved.[/dim]\n"
        )

    def _cmd_opt(self, args: list[str]) -> None:
        """opt on|off|show|history — toggle/inspect the prompt optimizer."""
        from rich.panel import Panel
        sub = args[0].lower() if args else "show"
        if sub == "on":
            self._prompt_opt = True
            self._console.print("[green]✓[/] Prompt optimizer [bold]ON[/] — messages will be optimized")
        elif sub == "off":
            self._prompt_opt = False
            self._console.print("[dim]Prompt optimizer [bold]OFF[/dim]")
        elif sub == "show":
            raw = getattr(self, "_last_raw", None)
            optimized = getattr(self, "_last_optimized", None)
            if raw and optimized:
                # Show BOTH sides side by side: what user typed vs what was sent
                self._console.print()
                self._console.print(Panel(
                    f"[yellow]{raw}[/yellow]",
                    title="[yellow bold]YOU SENT (raw input)[/yellow bold]",
                    border_style="yellow",
                    padding=(1, 2),
                ))
                self._console.print(Panel(
                    f"[green]{optimized}[/green]",
                    title="[green bold]AI RECEIVED (optimized prompt)[/green bold]",
                    border_style="green",
                    padding=(1, 2),
                ))
                raw_tokens = max(1, len(raw.split()))
                opt_tokens = max(1, int(len(optimized.split()) * 1.3))
                saved = max(0, round((raw_tokens - opt_tokens) / max(raw_tokens, 1) * 100))
                self._console.print(
                    f"[dim]Raw: {raw_tokens} tokens → Optimized: {opt_tokens} tokens "
                    f"({'+'if opt_tokens > raw_tokens else ''}{opt_tokens-raw_tokens} "
                    f"| {saved}% savings from compression after context injection)[/dim]"
                )
            elif optimized:
                self._console.print(Panel(optimized, title="Last optimized prompt", border_style="dim"))
            else:
                state = "ON" if self._prompt_opt else "OFF"
                self._console.print(f"[dim]Optimizer is [bold]{state}[/bold]. No prompt optimized yet.[/dim]")
        elif sub == "history":
            self._show_opt_history()
        else:
            self._console.print("[dim]opt on | opt off | opt show | opt history[/dim]")

    def _show_opt_history(self, limit: int = 10) -> None:
        import json

        from rich import box
        from rich.table import Table
        history_path = self._js._repo / ".jsat" / "prompt-history.jsonl"
        if not history_path.exists():
            self._console.print("[dim]No prompt history yet.[/dim]")
            return
        try:
            lines = history_path.read_text(encoding="utf-8").splitlines()
        except OSError as e:
            self._console.print(f"[red]Cannot read history:[/] {e}")
            return
        entries = []
        for raw in lines:
            raw = raw.strip()
            if not raw:
                continue
            try:
                entries.append(json.loads(raw))
            except Exception:
                pass
        recent = entries[-limit:]
        if not recent:
            self._console.print("[dim]No history entries.[/dim]")
            return
        t = Table(title=f"Prompt history (last {len(recent)})", box=box.SIMPLE, header_style="bold")
        t.add_column("#", width=4, style="dim")
        t.add_column("Task type", width=14)
        t.add_column("Tokens", width=14)
        t.add_column("Raw input")
        for idx, e in enumerate(recent, 1):
            before = e.get("tokens_before", "?")
            after = e.get("tokens_after", "?")
            t.add_row(str(idx), str(e.get("task_type", "?")), f"{before}→{after}", str(e.get("raw_input", ""))[:60])
        self._console.print(t)

    def _provider_hint(self, provider: str) -> str:
        hints = {
            "ollama":   "  [dim]Install: brew install ollama  →  ollama serve  →  ollama pull llama3.2[/dim]",
            "lmstudio": "  [dim]Open LM Studio → load a model → Local Server → Start[/dim]",
        }
        return hints.get(provider, "")

    def _show_ai(self) -> None:
        self._console.print(f"Current AI: [bold green]{self._ai_label()}[/]")
        self._console.print(
            f"  Provider: [cyan]{self._js._cfg.ai.provider}[/]\n"
            f"  Model:    [cyan]{self._js._cfg.ai.model}[/]\n"
            f"  Switch:   [dim]switch claude | switch gpt | switch ollama | switch gemini[/dim]"
        )

    # ── AI chat (the main feature) ────────────────────────────────────────────

    def _chat(self, message: str) -> None:
        """Send a message to the AI, auto-optimizing when self._prompt_opt is True."""
        # Auto-optimize through 7-stage pipeline
        prompt_to_send = message
        if self._prompt_opt:
            try:
                from jsat.tools.prompt_optimizer import PromptOptimizer
                opt = PromptOptimizer(graph=self._js._get_graph(), cfg=self._js._cfg, ai=self._js._get_ai())
                result = opt.optimize(message)
                self._last_optimized = result.optimized_prompt
                self._last_raw = message
                prompt_to_send = result.optimized_prompt
                saved = max(0, round((result.tokens_before - result.tokens_after) / max(result.tokens_before, 1) * 100))

                # Compact one-liner showing what changed
                self._console.print(
                    f"[dim]✦ Optimized[/dim] [cyan]{result.task_type}[/cyan] "
                    f"[dim]| {result.tokens_before}→{result.tokens_after} tokens "
                    f"({saved}% saved) | {len(result.context_nodes)} ctx nodes | "
                    f"format: {result.model_format} | "
                    f"[bold]opt show[/bold] to see full diff[/dim]"
                )
            except Exception:
                prompt_to_send = message  # fallback silently

        try:
            ai = self._js._get_ai()
        except Exception as e:
            self._console.print(
                f"[red]No AI available:[/] {e}\n"
                "Configure one: [bold]switch claude[/] | [bold]switch gpt[/] | "
                "[bold]switch ollama[/]"
            )
            return

        if not ai.is_available():
            self._console.print(
                f"[yellow]⚠ {self._ai_label()} is not reachable.[/]\n"
                "Switch: [bold]switch claude[/] | [bold]switch gpt[/] | [bold]switch ollama[/]\n"
                + self._provider_hint(self._js._cfg.ai.provider)
            )
            return

        # Build prompt — use optimizer output if available, otherwise inject context
        prompt = self._build_chat_prompt(prompt_to_send)

        # Stream response
        self._console.print(f"[dim]{self._ai_label()}:[/dim] ", end="")
        t0 = time.monotonic()
        total = 0
        try:
            for chunk in ai.stream(prompt, max_tokens=2048):
                print(chunk, end="", flush=True)
                total += len(chunk)
            print()  # newline after stream
            elapsed = round(time.monotonic() - t0, 1)
            self._console.print(f"[dim]{elapsed}s · {total} chars[/dim]")
        except Exception as e:
            print()
            self._console.print(f"[red]Stream error:[/] {e}")

    def _build_chat_prompt(self, message: str) -> str:
        """Inject minimal codebase context when graph has data."""
        try:
            status = self._js.index_status
            if status.get("nodes", 0) > 0:
                # Pull a few key graph facts as context
                ctx_lines = [
                    f"Repository: {self._js._repo.name}",
                    f"Graph: {status['nodes']:,} nodes, {status['edges']:,} edges",
                ]
                try:
                    services = self._js._get_graph().query("MATCH (n:Service) RETURN n")[:5]
                    for s in services:
                        ctx_lines.append(f"Service: {s.get('properties',{}).get('name','?')}")
                except Exception:
                    pass

                context = "\n".join(ctx_lines)
                return (
                    f"You are an expert software engineer with full knowledge of this codebase.\n\n"
                    f"CODEBASE CONTEXT:\n{context}\n\n"
                    f"USER: {message}\n\nASSISTANT:"
                )
        except Exception:
            pass

        # No graph — plain AI chat
        return message

    # ── JSAT tool commands ────────────────────────────────────────────────────

    def _help(self) -> None:
        from rich import box
        from rich.table import Table
        table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
        table.add_column("Command", style="bold cyan", min_width=22)
        table.add_column("Description")
        for cmd, desc in _COMMANDS.items():
            table.add_row(cmd, desc)
        self._console.print(table)
        self._console.print(
            "\n[dim]Anything else → sent to the AI as a chat message.[/dim]\n"
        )

    def _exit(self) -> None:
        self._console.print("[dim]Goodbye.[/dim]")
        self._running = False

    def _cmd_index(self, args: list[str]) -> None:
        path = args[0] if args else "."
        self._console.print(f"[dim]Indexing {path}...[/dim]")
        t0 = time.monotonic()
        result = self._js.index(path=path)
        elapsed = round(time.monotonic() - t0, 1)
        self._console.print(
            f"[green]✓[/] {result.nodes_indexed:,} nodes · "
            f"{result.edges_indexed:,} edges · {elapsed}s"
        )

    def _cmd_blast_radius(self, args: list[str]) -> None:
        if not args:
            self._console.print("[red]Usage:[/] blast-radius <FILE_OR_SYMBOL>")
            return
        target = " ".join(args)
        self._console.print("[dim]Tracing...[/dim]")
        report = self._js.blast_radius(target)
        s = report.summary
        self._console.print(
            f"[red]Breaking: {s.get('breaking',0)}[/]  "
            f"[yellow]Degraded: {s.get('degraded',0)}[/]  "
            f"[cyan]Warning: {s.get('warning',0)}[/]  "
            f"[green]Safe: {s.get('safe',0)}[/]"
        )
        for imp in report.impacts[:10]:
            _c = {"breaking":"red","degraded":"yellow","warning":"cyan","safe":"green"}
            color = _c.get(imp.severity, "white")
            self._console.print(f"  [{color}]{imp.severity:10}[/{color}] {imp.node_name[:50]}")

    def _cmd_test_gaps(self, args: list[str]) -> None:
        from jsat.tools.test_helper import TestHelperTool
        service = args[0] if args else None
        self._console.print("[dim]Analyzing...[/dim]")
        tool = TestHelperTool(graph=self._js._get_graph(), cfg=self._js._cfg)
        r = tool.run(service=service)
        self._console.print(
            f"Coverage: [bold]{r.coverage_pct:.1f}%[/]  "
            f"Untested: [red]{len(r.untested_functions)}[/]  "
            f"Over-mocked: [yellow]{len(r.over_mocked_tests)}[/]"
        )
        for fn in r.untested_functions[:6]:
            self._console.print(f"  [dim]✗[/] {fn}")

    def _cmd_feature(self, args: list[str]) -> None:
        if not args:
            self._console.print("[red]Usage:[/] feature <DESCRIPTION>")
            return
        desc = " ".join(args)
        self._console.print("[dim]Planning...[/dim]")
        from jsat.tools.feature import FeatureTool
        plan = FeatureTool(graph=self._js._get_graph(), cfg=self._js._cfg,
                           ai=self._js._get_ai()).run(desc)
        self._console.print(f"Complexity: [bold]{plan.estimated_complexity}[/]")
        for i, step in enumerate(plan.implementation_steps[:6], 1):
            self._console.print(f"  {i}. {step}")

    def _cmd_contract(self, args: list[str]) -> None:
        base = args[0] if args else "main"
        self._console.print(f"[dim]Checking vs {base}...[/dim]")
        from jsat.tools.contract import ContractTool
        r = ContractTool(graph=self._js._get_graph(), cfg=self._js._cfg).run(base=base)
        color = "red" if r.breaking_count else "green"
        self._console.print(f"Compat: [{color}]{r.compat_score}/100[/{color}]  Breaking: [{color}]{r.breaking_count}[/{color}]")

    def _cmd_security(self, args: list[str]) -> None:
        path = Path(args[0]) if args else Path(".")
        self._console.print("[dim]Scanning...[/dim]")
        r = self._js.security_review(path=path)
        crit = sum(1 for f in r.findings if f.severity == "critical")
        self._console.print(f"[red]Critical: {crit}[/]  Total: {len(r.findings)}  Secrets: {r.secrets_found}")
        for f in r.findings[:5]:
            color = "red" if f.severity == "critical" else "yellow"
            self._console.print(f"  [{color}]{f.severity}[/{color}] {f.title} — {f.file}:{f.line}")

    def _cmd_incident(self, args: list[str]) -> None:
        if not args:
            self._console.print("[red]Usage:[/] incident <DESCRIPTION>")
            return
        r = self._js.investigate_incident(" ".join(args))
        for i, h in enumerate(r.hypotheses[:3], 1):
            bar = "█" * int(h.score * 10)
            self._console.print(f"  [bold]{i}.[/] ({h.score:.2f}) [cyan]{bar}[/]  {h.commit_summary[:60]}")

    def _cmd_migrate(self, args: list[str]) -> None:
        if not args:
            self._console.print("[red]Usage:[/] migrate-check <FILE>")
            return
        from jsat.tools.migration import MigrationTool
        r = MigrationTool(graph=self._js._get_graph(), cfg=self._js._cfg).run(Path(args[0]))
        color = {"safe":"green","warning":"yellow","dangerous":"red"}.get(r.risk_level, "white")
        self._console.print(f"Risk: [{color}]{r.risk_level}[/{color}]  Lock: {r.lock_estimate_seconds:.1f}s  Rollback: {'yes' if r.has_rollback else 'no'}")

    def _cmd_review(self, args: list[str]) -> None:
        base = args[0] if args else "main"
        self._console.print(f"[dim]Reviewing vs {base}...[/dim]")
        from jsat.tools.review import ReviewTool
        r = ReviewTool(graph=self._js._get_graph(), cfg=self._js._cfg, ai=self._js._get_ai()).run(base=base)
        self._console.print(f"Findings: [bold]{len(r.findings)}[/]  High confidence: [red]{len(r.high_confidence)}[/]")
        for f in r.high_confidence[:5]:
            self._console.print(f"  [red]●[/] {f.title} ({f.file}:{f.line})")

    def _cmd_knowledge(self, args: list[str]) -> None:
        from jsat.tools.knowledge import KnowledgeTool
        tool = KnowledgeTool(graph=self._js._get_graph(), cfg=self._js._cfg, ai=self._js._get_ai())
        sub = args[0].lower() if args else "help"
        rest = " ".join(args[1:])
        if sub == "add":
            tool.add(rest); self._console.print("[green]✓[/] Stored.")
        elif sub == "query":
            r = tool.query(rest); self._console.print(f"[green]→[/] {r.answer}")
        elif sub == "list":
            for e in tool.list_entries()[:8]:
                self._console.print(f"  [dim]{e['category']}[/] {e['text'][:60]}")
        else:
            self._console.print("[dim]Subcommands: add, query, list[/dim]")

    def _cmd_export(self, args: list[str]) -> None:
        if not args:
            self._console.print("[red]Usage:[/] export <OUTPUT>")
            return
        m = self._js.export(args[0])
        self._console.print(f"[green]✓[/] Exported to [bold]{args[0]}[/] ({m.size_mb:.1f} MB)")

    def _cmd_doctor(self, _: list[str]) -> None:
        r = self._js.doctor()
        g, ai, idx = r.get("graph",{}), r.get("ai",{}), r.get("index",{})
        self._console.print(f"Profile: [bold]{r.get('profile','?')}[/]  AI: {'[green]✓[/]' if ai.get('ok') else '[red]✗[/]'} {ai.get('provider')}/{ai.get('model')}  Graph: {'[green]✓[/]' if g.get('ok') else '[red]✗[/]'} {g.get('backend')}")
        self._console.print(f"Index: [bold]{idx.get('nodes',0):,}[/] nodes · [bold]{idx.get('edges',0):,}[/] edges")

    def _cmd_status(self, _: list[str]) -> None:
        s = self._js.index_status
        self._console.print(f"Nodes: [bold]{s.get('nodes',0):,}[/]  Edges: [bold]{s.get('edges',0):,}[/]  AI: [bold]{self._ai_label()}[/]")


def launch(jsat: JSAT) -> None:
    """Entry point called by the CLI."""
    JSATShell(jsat).run()


# ── Standalone launcher (called from CLI) ─────────────────────────────────────

def launch_ai_with_jsat_tools(jsat: "JSAT", ai: str = "claude") -> None:
    """Launch an AI session with JSAT tools wired in as MCP.

    ai: "claude" | "gpt" | "ollama" | ... — which AI CLI to launch.
    For now only "claude" is supported; others fall back to JSAT REPL.
    """
    import json
    import os
    import shutil
    import subprocess
    import tempfile

    repo = str(jsat._repo)
    idx = jsat.index_status
    nodes = idx.get("nodes", 0)
    edges = idx.get("edges", 0)

    if ai in ("claude", "claude-cli") and shutil.which("claude"):
        jsat_bin = shutil.which("jsat") or sys.argv[0]

        mcp_config = {
            "mcpServers": {
                "jsat": {
                    "command": jsat_bin,
                    "args": ["mcp-server", "--repo", repo],
                    "env": {},
                }
            }
        }

        jsat_context = (
            f"You are working in the codebase at: {repo}\n"
            f"JSAT graph: {nodes:,} nodes, {edges:,} edges.\n\n"
            "JSAT MCP tools available to you (use proactively for codebase questions):\n"
            "  jsat__query              — answer any codebase question from the graph\n"
            "  jsat__blast_radius       — trace downstream impact of any file/symbol change\n"
            "  jsat__security_review    — find security issues and secrets\n"
            "  jsat__investigate_incident — score commits as incident hypotheses\n"
            "  jsat__index_repo         — rebuild the codebase graph\n"
            "  jsat__get_index_status   — graph stats\n"
            "  jsat__export_index       — export graph as zip\n"
            "  jsat__get_jsat_version   — JSAT version info\n\n"
            "You also have /jsat-* slash commands available if skills are installed.\n"
            "Run 'jsat connect claude --install-skills' to install them."
        )

        mcp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False, prefix="jsat-mcp-"
            ) as f:
                json.dump(mcp_config, f, indent=2)
                mcp_path = f.name

            subprocess.run([
                "claude",
                "--mcp-config", mcp_path,
                "--add-dir", repo,
                "--append-system-prompt", jsat_context,
            ])
        finally:
            if mcp_path:
                try:
                    os.unlink(mcp_path)
                except Exception:
                    pass
    else:
        # Fallback: custom JSAT shell
        launch(jsat)
