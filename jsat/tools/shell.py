"""
jsat.tools.shell — Tool 0: Interactive REPL for codebase intelligence.

Launch: jsat shell  (or run this module directly)

Features:
  - Natural language Q&A over the indexed codebase
  - All JSAT tools accessible as shell commands
  - Tab completion over tool names and common keywords
  - Session history (up/down arrows)
  - Structured Rich output: tables, color-coded severity
  - `help` shows all available commands
  - `exit` / Ctrl-D to quit
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

# ── Commands available in the shell ──────────────────────────────────────────

_COMMANDS: dict[str, str] = {
    "index":          "index [PATH] — build/update the codebase graph",
    "blast-radius":   "blast-radius <FILE> — trace downstream impact",
    "test-gaps":      "test-gaps [SERVICE] — find untested code paths",
    "feature":        "feature <DESCRIPTION> — generate implementation plan",
    "contract-check": "contract-check [BASE] — validate API contract changes",
    "security-review":"security-review [PATH] — run OWASP + secret scan",
    "incident":       "incident <DESCRIPTION> — investigate a production incident",
    "migrate-check":  "migrate-check <FILE> — validate a migration file",
    "review":         "review [BASE] — multi-model code review",
    "knowledge":      "knowledge add|query|list <TEXT>",
    "export":         "export <OUTPUT> — export index as zip",
    "doctor":         "doctor — run system health check",
    "status":         "status — show index statistics",
    "skills":         "skills list|run <NAME>",
    "help":           "help — show this message",
    "exit":           "exit / quit / Ctrl-D — leave the shell",
}

_COMPLETIONS = sorted(_COMMANDS.keys()) + ["query", "quit"]


class JSATShell:
    """Interactive REPL backed by a JSAT instance."""

    BANNER = (
        "\n[bold cyan]JSAT Shell[/] [dim]v0.1.0[/] — Codebase Intelligence\n"
        "[dim]Type [bold]help[/bold] for commands, ask anything in natural language, or [bold]exit[/bold] to quit.[/dim]\n"
    )

    def __init__(self, jsat: JSAT) -> None:
        from rich.console import Console
        import structlog

        self._js = jsat
        self._console = Console()
        self._log = structlog.get_logger(__name__)
        self._running = False
        self._setup_readline()

    # ── Setup ─────────────────────────────────────────────────────────────────

    def _setup_readline(self) -> None:
        """Enable history and tab completion."""
        try:
            history_path = Path.home() / ".jsat_history"
            if history_path.exists():
                readline.read_history_file(str(history_path))
            readline.set_history_length(1000)

            def completer(text: str, state: int) -> str | None:
                options = [c for c in _COMPLETIONS if c.startswith(text)]
                return options[state] if state < len(options) else None

            readline.set_completer(completer)
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

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self) -> None:
        """Start the REPL. Blocks until user exits."""
        self._console.print(self.BANNER)

        # Show index status on startup
        status = self._js.index_status
        if status.get("nodes", 0) > 0:
            self._console.print(
                f"[dim]Index: {status['nodes']:,} nodes, "
                f"{status['edges']:,} edges[/dim]\n"
            )
        else:
            self._console.print(
                "[yellow]Index not built. Run:[/] [bold]index .[/bold]\n"
            )

        self._running = True
        while self._running:
            try:
                raw = input("jsat> ").strip()
            except (EOFError, KeyboardInterrupt):
                self._console.print("\n[dim]Goodbye.[/dim]")
                break

            if not raw:
                continue

            self._log.debug("shell_input", raw=raw[:120])
            self._dispatch(raw)

        self._save_history()

    # ── Dispatch ──────────────────────────────────────────────────────────────

    def _dispatch(self, raw: str) -> None:
        """Route input to a named command or the natural-language query handler."""
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
            "skills":         self._cmd_skills,
        }

        if cmd in handlers:
            try:
                handlers[cmd](args)
            except Exception as e:
                self._console.print(f"[red]Error:[/] {e}")
                self._log.error("shell_command_error", cmd=cmd, error=str(e))
        else:
            # Treat anything else as a natural-language query
            self._cmd_query(raw)

    # ── Command implementations ───────────────────────────────────────────────

    def _help(self) -> None:
        from rich.table import Table
        from rich import box
        table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
        table.add_column("Command", style="bold cyan", min_width=20)
        table.add_column("Description")
        for cmd, desc in _COMMANDS.items():
            table.add_row(cmd, desc)
        self._console.print(table)

    def _exit(self) -> None:
        self._console.print("[dim]Goodbye.[/dim]")
        self._running = False

    def _cmd_query(self, question: str) -> None:
        t0 = time.monotonic()
        self._console.print(f"[dim]Querying...[/dim]", end="\r")
        try:
            result = self._js.query(question)
            elapsed = round(time.monotonic() - t0, 2)
            self._console.print(f"[green]→[/] {result.answer}")
            self._console.print(f"[dim]{elapsed}s | confidence: {result.confidence:.0%}[/dim]")
        except Exception as e:
            self._console.print(f"[red]Query failed:[/] {e}")

    def _cmd_index(self, args: list[str]) -> None:
        path = args[0] if args else "."
        self._console.print(f"[dim]Indexing {path}...[/dim]")
        t0 = time.monotonic()
        result = self._js.index(path=path)
        elapsed = round(time.monotonic() - t0, 1)
        self._console.print(
            f"[green]✓[/] Indexed [bold]{result.nodes_indexed:,}[/] nodes, "
            f"[bold]{result.edges_indexed:,}[/] edges in [bold]{elapsed}s[/]"
        )

    def _cmd_blast_radius(self, args: list[str]) -> None:
        if not args:
            self._console.print("[red]Usage:[/] blast-radius <FILE_OR_SYMBOL>")
            return
        target = " ".join(args)
        self._console.print(f"[dim]Tracing blast radius for {target}...[/dim]")
        report = self._js.blast_radius(target)
        self._print_blast_radius(report)

    def _print_blast_radius(self, report: object) -> None:
        from rich.table import Table
        from rich import box

        summary = getattr(report, "summary", {})
        self._console.print(
            f"[red]Breaking: {summary.get('breaking', 0)}[/]  "
            f"[yellow]Degraded: {summary.get('degraded', 0)}[/]  "
            f"[cyan]Warning: {summary.get('warning', 0)}[/]  "
            f"[green]Safe: {summary.get('safe', 0)}[/]"
        )
        impacts = getattr(report, "impacts", [])[:15]
        if impacts:
            table = Table(box=box.SIMPLE, show_header=True, header_style="bold")
            table.add_column("Severity", min_width=10)
            table.add_column("Node")
            table.add_column("Type")
            table.add_column("Via")
            _sev_color = {"breaking": "red", "degraded": "yellow",
                          "warning": "cyan", "safe": "green"}
            for imp in impacts:
                sev = getattr(imp, "severity", "safe")
                color = _sev_color.get(sev, "white")
                table.add_row(
                    f"[{color}]{sev}[/{color}]",
                    getattr(imp, "node_name", "?")[:40],
                    getattr(imp, "node_type", "?"),
                    " → ".join(getattr(imp, "path", [])[-2:]),
                )
            self._console.print(table)

    def _cmd_test_gaps(self, args: list[str]) -> None:
        from jsat.tools.test_helper import TestHelperTool
        service = args[0] if args else None
        self._console.print("[dim]Analyzing test coverage...[/dim]")
        tool = TestHelperTool(graph=self._js._get_graph(), cfg=self._js._cfg)
        report = tool.run(service=service)
        self._console.print(
            f"Coverage: [bold]{report.coverage_pct:.1f}%[/]  "
            f"Untested: [red]{len(report.untested_functions)}[/] functions  "
            f"Over-mocked: [yellow]{len(report.over_mocked_tests)}[/] tests"
        )
        for fn in report.untested_functions[:8]:
            self._console.print(f"  [dim]✗[/] {fn}")

    def _cmd_feature(self, args: list[str]) -> None:
        if not args:
            self._console.print("[red]Usage:[/] feature <DESCRIPTION>")
            return
        desc = " ".join(args)
        self._console.print(f"[dim]Planning feature: {desc[:60]}...[/dim]")
        from jsat.tools.feature import FeatureTool
        tool = FeatureTool(graph=self._js._get_graph(), cfg=self._js._cfg,
                            ai=self._js._get_ai())
        plan = tool.run(desc)
        self._console.print(f"Complexity: [bold]{plan.estimated_complexity}[/]")
        for i, step in enumerate(plan.implementation_steps[:6], 1):
            self._console.print(f"  {i}. {step}")

    def _cmd_contract(self, args: list[str]) -> None:
        base = args[0] if args else "main"
        self._console.print(f"[dim]Checking API contracts vs {base}...[/dim]")
        from jsat.tools.contract import ContractTool
        tool = ContractTool(graph=self._js._get_graph(), cfg=self._js._cfg)
        report = tool.run(base=base)
        color = "red" if report.breaking_count else "green"
        self._console.print(
            f"Compat score: [{color}]{report.compat_score}/100[/{color}]  "
            f"Breaking: [{color}]{report.breaking_count}[/{color}]"
        )

    def _cmd_security(self, args: list[str]) -> None:
        path = Path(args[0]) if args else Path(".")
        self._console.print(f"[dim]Scanning {path} for security issues...[/dim]")
        report = self._js.security_review(path=path)
        crit = sum(1 for f in report.findings if f.severity == "critical")
        high = sum(1 for f in report.findings if f.severity == "high")
        self._console.print(
            f"[red]Critical: {crit}[/]  [yellow]High: {high}[/]  "
            f"Total: {len(report.findings)}  Secrets: {report.secrets_found}"
        )
        for f in report.findings[:5]:
            color = "red" if f.severity == "critical" else "yellow"
            self._console.print(f"  [{color}]{f.severity}[/{color}] {f.title} — {f.file}:{f.line}")

    def _cmd_incident(self, args: list[str]) -> None:
        if not args:
            self._console.print("[red]Usage:[/] incident <DESCRIPTION>")
            return
        desc = " ".join(args)
        self._console.print(f"[dim]Investigating: {desc[:60]}...[/dim]")
        report = self._js.investigate_incident(desc)
        for i, h in enumerate(report.hypotheses[:3], 1):
            bar = "█" * int(h.score * 10)
            self._console.print(
                f"  [bold]{i}.[/] (score {h.score:.2f}) [cyan]{bar}[/cyan]  {h.commit_summary[:60]}"
            )

    def _cmd_migrate(self, args: list[str]) -> None:
        if not args:
            self._console.print("[red]Usage:[/] migrate-check <MIGRATION_FILE>")
            return
        from jsat.tools.migration import MigrationTool
        tool = MigrationTool(graph=self._js._get_graph(), cfg=self._js._cfg)
        report = tool.run(Path(args[0]))
        color = {"safe": "green", "warning": "yellow", "dangerous": "red"}.get(report.risk_level, "white")
        self._console.print(
            f"Risk: [{color}]{report.risk_level}[/{color}]  "
            f"Lock est: {report.lock_estimate_seconds:.1f}s  "
            f"Has rollback: {'yes' if report.has_rollback else 'no'}"
        )

    def _cmd_review(self, args: list[str]) -> None:
        base = args[0] if args else "main"
        self._console.print(f"[dim]Running code review vs {base}...[/dim]")
        from jsat.tools.review import ReviewTool
        tool = ReviewTool(graph=self._js._get_graph(), cfg=self._js._cfg,
                          ai=self._js._get_ai())
        report = tool.run(base=base)
        self._console.print(
            f"Findings: [bold]{len(report.findings)}[/]  "
            f"High confidence: [red]{len(report.high_confidence)}[/]"
        )
        for f in report.high_confidence[:5]:
            self._console.print(f"  [red]●[/] {f.title} ({f.file}:{f.line})")

    def _cmd_knowledge(self, args: list[str]) -> None:
        from jsat.tools.knowledge import KnowledgeTool
        tool = KnowledgeTool(graph=self._js._get_graph(), cfg=self._js._cfg,
                              ai=self._js._get_ai())
        sub = args[0].lower() if args else "help"
        rest = " ".join(args[1:])

        if sub == "add":
            if not rest:
                self._console.print("[red]Usage:[/] knowledge add <TEXT>")
                return
            tool.add(rest)
            self._console.print("[green]✓[/] Knowledge stored.")

        elif sub == "query":
            if not rest:
                self._console.print("[red]Usage:[/] knowledge query <QUESTION>")
                return
            result = tool.query(rest)
            self._console.print(f"[green]→[/] {result.answer}")
            self._console.print(f"[dim]confidence: {result.confidence:.0%}[/dim]")

        elif sub == "list":
            entries = tool.list_entries()
            if not entries:
                self._console.print("[dim]No entries yet. Use: knowledge add <TEXT>[/dim]")
            for e in entries[:10]:
                self._console.print(f"  [dim]{e['id'][:16]}[/] [{e['category']}] {e['text'][:60]}")
        else:
            self._console.print("[dim]Subcommands: add, query, list[/dim]")

    def _cmd_export(self, args: list[str]) -> None:
        if not args:
            self._console.print("[red]Usage:[/] export <OUTPUT_PATH>")
            return
        manifest = self._js.export(args[0])
        self._console.print(
            f"[green]✓[/] Exported to [bold]{args[0]}[/] ({manifest.size_mb:.1f} MB)"
        )

    def _cmd_doctor(self, _: list[str]) -> None:
        report = self._js.doctor()
        g = report.get("graph", {})
        ai = report.get("ai", {})
        idx = report.get("index", {})
        self._console.print(f"Profile: [bold]{report.get('profile', '?')}[/]")
        self._console.print(
            f"Graph:   {'[green]✓[/]' if g.get('ok') else '[red]✗[/]'} "
            f"{g.get('backend', '?')}"
        )
        self._console.print(
            f"AI:      {'[green]✓[/]' if ai.get('ok') else '[red]✗[/]'} "
            f"{ai.get('provider', '?')}/{ai.get('model', '?')}"
        )
        self._console.print(
            f"Index:   [bold]{idx.get('nodes', 0):,}[/] nodes, "
            f"[bold]{idx.get('edges', 0):,}[/] edges"
        )

    def _cmd_status(self, _: list[str]) -> None:
        s = self._js.index_status
        self._console.print(
            f"Nodes: [bold]{s.get('nodes', 0):,}[/]  "
            f"Edges: [bold]{s.get('edges', 0):,}[/]  "
            f"Commit: [dim]{s.get('commit', 'none')}[/dim]"
        )

    def _cmd_skills(self, args: list[str]) -> None:
        from jsat.skills.registry import SkillsRegistry
        registry = SkillsRegistry(self._js._cfg.skills.dir)
        sub = args[0].lower() if args else "list"

        if sub == "list":
            skills = registry.list_skills()
            if not skills:
                self._console.print("[dim]No skills installed. Add YAML manifests to skills/[/dim]")
            for s in skills:
                self._console.print(f"  [cyan]{s['name']}[/] v{s['version']} — {s['description']}")
        elif sub == "run" and len(args) >= 2:
            name = args[1]
            kwargs = dict(a.split("=", 1) for a in args[2:] if "=" in a)
            result = registry.run(name, **kwargs)
            self._console.print(result)
        else:
            self._console.print("[dim]Subcommands: list, run <NAME> [key=val...][/dim]")


def launch(jsat: JSAT) -> None:
    """Entry point called by the CLI."""
    shell = JSATShell(jsat)
    shell.run()
