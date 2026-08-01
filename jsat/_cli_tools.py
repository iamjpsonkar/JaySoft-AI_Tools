"""
jsat._cli_tools — Tool commands (crack, short, prompt, tokens, knowledge-ingest).
"""
from __future__ import annotations

import contextlib
from pathlib import Path

import structlog
import typer
from rich import box
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from ._cli_common import _jsat, app, console, err

_log = structlog.get_logger(__name__)

# ── crack ─────────────────────────────────────────────────────────────────────

@app.command("crack", rich_help_panel="⚡  Tools")
def cmd_crack(
    task: str = typer.Argument(..., help="The complex engineering task to discuss"),
    roles: str | None = typer.Option(
        None, "--roles", "-r",
        help="Comma-separated subset: architect,security,implementer,tester,skeptic",
    ),
    rounds: int = typer.Option(3, "--rounds", "-n", help="Discussion rounds (default 3)"),
    file: str | None = typer.Option(None, "--file", "-f", help="Write output to file"),
    repo: str = typer.Option(".", "--repo"),
) -> None:
    """Run a multi-agent war room on a complex engineering decision.

    \b
    Six specialist agents (architect, security, implementer, tester, skeptic,
    moderator) discuss the task in rounds. Each agent responds to others'
    arguments. The moderator synthesizes consensus and an action plan.

    \b
    Examples:
      jsat crack "redesign payment retry system"
      jsat crack --roles architect,security "migrate users table to UUID"
      jsat crack --rounds 2 --file design.md "sync vs async webhooks"
    """
    from jsat.tools.crack import CrackTool
    js = _jsat(repo=repo)
    role_list = [r.strip() for r in roles.split(",")] if roles else None

    with Progress(SpinnerColumn(), TextColumn("{task.description}"),
                  console=console, transient=True) as p:
        p.add_task(f"War room: [bold]{task[:50]}[/]…", total=None)
        result = CrackTool(
            graph=js._get_graph(), cfg=js._cfg, ai=js._get_ai()
        ).run(task, roles=role_list, rounds=rounds, output_file=file,
              repo_path=Path(repo).resolve())

    if not result.ai_available:
        err.print("[yellow]⚠ AI not configured — showing structural placeholders.[/]")
        err.print("[dim]  Run: jsat ai use claude-cli   (or any provider)[/dim]\n")

    # Print discussion summary
    for r in range(1, result.rounds_run + 1):
        console.print(f"\n[bold]Round {r}[/]")
        for s in (st for st in result.statements if st.round_num == r and st.role != "moderator"):
            emoji = {
                "architect": "🏛", "security": "🔒", "implementer": "⚙️",
                "tester": "🧪", "skeptic": "😈",
            }.get(s.role, "•")
            console.print(f"\n  {emoji} [bold]{s.role.upper()}[/]")
            console.print(f"  {s.text[:300]}{'…' if len(s.text)>300 else ''}")

    console.print("\n" + "─" * 60)
    console.print("[bold green]🎯 Final Synthesis[/]\n")
    console.print(result.synthesis or "[dim]No synthesis — AI unavailable.[/dim]")

    if result.output_path:
        console.print(f"\n[dim]Full discussion saved to [cyan]{result.output_path}[/][/dim]")
    console.print(
        f"[dim]{result.rounds_run} rounds · {len(result.roles)} agents · "
        f"{result.elapsed_ms:.0f}ms[/dim]"
    )


# ── short ─────────────────────────────────────────────────────────────────────

@app.command("short", rich_help_panel="⚡  Tools")
def cmd_short(
    query: str = typer.Argument(..., help="Question to ask"),
    words: int = typer.Option(50, "--words", "-w", help="Max word count (default 50)"),
    one_line: bool = typer.Option(False, "--one-line", "-1", help="Strict one-sentence answer"),
    repo: str = typer.Option(".", "--repo", "-r"),
) -> None:
    """Ask any question — get the shortest possible correct answer.

    \b
    jsat short "what does process_refund do"
    jsat short --one-line "is PaymentService.process async"
    jsat short --words 20 "explain the retry logic"
    """
    js = _jsat(repo=repo)
    ai = js._get_ai()
    if not ai.is_available():
        err.print(f"[red]AI not reachable:[/] {js.active_ai_label()}")
        raise typer.Exit(1)

    if one_line:
        constraint = "Answer in exactly one sentence. No preamble, no bullet points."
    else:
        constraint = f"Answer in ≤{words} words. Plain language. No preamble or headers."

    full_query = f"{constraint}\n\n{query}"
    console.print(f"[dim]{js.active_ai_label()}:[/dim] ", end="")
    for chunk in ai.stream(full_query, max_tokens=256):
        print(chunk, end="", flush=True)
    print()

# ── prompt ────────────────────────────────────────────────────────────────────

@app.command("prompt", rich_help_panel="⚡  Tools")
def cmd_prompt(
    input_text: str = typer.Argument(..., help="Raw query to optimize"),
    send: bool = typer.Option(False, "--send", "-s", help="Send to AI and return response"),
    ai: str | None = typer.Option(None, "--ai", help="AI override: claude|gpt|ollama"),
    format: str | None = typer.Option(None, "--format", "-f", help="code|plan|json|prose"),
    cot: bool = typer.Option(False, "--cot", help="Enable chain-of-thought"),
    compress: bool = typer.Option(True, "--compress/--no-compress"),
    no_context: bool = typer.Option(False, "--no-context"),
    no_examples: bool = typer.Option(False, "--no-examples"),
    self_critique: bool = typer.Option(
        False, "--self-critique", help="Run critique pass on response (high-stakes tasks)"
    ),
    rewrite: bool = typer.Option(
        False, "--rewrite", help="Run 1 LLM rewrite agent after offline pipeline"
    ),
    n_agents: int = typer.Option(
        0, "--agents", help="Run N parallel LLM rewrite agents (1-3; omit N for 3)"
    ),
    diff: bool = typer.Option(False, "--diff", help="Show raw vs optimized"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    max_tokens: int = typer.Option(4096, "--max-tokens"),
    repo: str = typer.Option(".", "--repo", "-r"),
) -> None:
    """Optimize any query into the best possible prompt for your AI.

    \b
    Print optimized prompt:       jsat prompt "improve the retry logic"
    Send to AI:                   jsat prompt --send "improve the retry logic"
    LLM rewrite (1 agent):        jsat prompt --rewrite "fix logger in payments"
    Multi-agent rewrite (3):      jsat prompt --agents "fix logger in payments"
    Specific AI + format:         jsat prompt --send --ai claude --format code "test refund()"
    Show transformation:          jsat prompt --diff --verbose "refactor webhook handler"
    """
    # --agents without a value defaults to 3
    if n_agents == 0 and rewrite:
        n_agents = 1
    js = _jsat(repo=repo, verbose=verbose)
    try:
        from jsat.tools.prompt_optimizer import PromptOptimizer
        optimizer = PromptOptimizer(graph=js._get_graph(), cfg=js._cfg, ai=js._get_ai())
    except Exception as e:
        err.print(f"[red]PromptOptimizer error:[/] {e}")
        raise typer.Exit(1) from e

    _rewrite_msg = " (+ LLM rewriting...)" if n_agents > 0 else ""
    console.print(f"[dim]Optimizing{_rewrite_msg}[/dim]", end="\r")
    try:
        result = optimizer.optimize(
            input_text, ai_provider=ai, output_format=format, cot=cot,
            compress=compress, max_context_tokens=max_tokens,
            no_context=no_context, no_examples=no_examples,
            rewrite=rewrite, n_agents=n_agents,
        )
    except Exception as e:
        err.print(f"[red]Optimization failed:[/] {e}")
        raise typer.Exit(1) from e

    if verbose:
        t = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
        t.add_column("Metric", style="bold cyan")
        t.add_column("Value")
        t.add_row("Task type", result.task_type)
        t.add_row("Model format", result.model_format)
        t.add_row("Context nodes", str(len(result.context_nodes)))
        t.add_row("Examples used", str(result.examples_used))
        t.add_row("Tokens before", str(result.tokens_before))
        t.add_row("Tokens after", str(result.tokens_after))
        if result.tokens_before:
            saved = max(
                0,
                round((result.tokens_before - result.tokens_after) / result.tokens_before * 100),
            )
            t.add_row("Compression", f"{saved}% saved")
        if result.rewrite_applied:
            t.add_row("", "")
            t.add_row("[dim]LLM rewriting[/dim]", "[dim](phase 2)[/dim]")
            t.add_row("  Agents run", str(result.rewrite_agents_run))
            t.add_row("  Winner", result.winning_agent or "—")
            t.add_row("  Rewrite time", f"{result.rewrite_elapsed_ms:.0f}ms")
        if result.agent_timings:
            t.add_row("", "")
            t.add_row("[dim]Offline timings[/dim]", "[dim](zero LLM)[/dim]")
            for agent, ms in result.agent_timings.items():
                if not agent.startswith("rewrite_"):
                    t.add_row(f"  {agent}", f"  {ms}ms")
        console.print(Panel(t, title="Prompt Pipeline", border_style="dim"))

    if diff:
        console.print(Panel(input_text, title="[yellow]Raw input[/]", border_style="yellow"))
        console.print(
            Panel(result.optimized_prompt, title="[green]Optimized[/]", border_style="green")
        )

    if getattr(result, "rewrite_skip_reason", None):
        reason = result.rewrite_skip_reason
        if reason == "ai_unavailable":
            err.print(
                "[yellow]⚠ LLM rewrite requested but skipped — "
                "no AI provider configured.[/]"
            )
            err.print("[dim]  Configure one with: jsat ai use <provider>[/dim]")
        else:
            err.print(f"[yellow]⚠ LLM rewrite skipped: {reason}[/]")

    if result.tokens_before and result.tokens_after:
        saved = max(
            0,
            round((result.tokens_before - result.tokens_after) / result.tokens_before * 100),
        )
        rewrite_tag = (
            f" | {result.rewrite_agents_run} agents → {result.winning_agent} won"
            if result.rewrite_applied
            else ""
        )
        console.print(
            f"[dim]Tokens: {result.tokens_before} → {result.tokens_after} ({saved}% saved) "
            f"| Task: {result.task_type}{rewrite_tag}[/dim]"
        )

    if not send or dry_run:
        if not diff:
            console.print(
                Panel(result.optimized_prompt, title="Optimized prompt", border_style="cyan")
            )
        if dry_run:
            console.print("[dim][dry-run] Not sending.[/dim]")
        return

    # Send to AI
    console.print(f"\n[dim]Sending to {js.active_ai_label()}...[/dim]\n")
    ai_provider = js._get_ai()
    if not ai_provider.is_available():
        err.print(f"[red]AI not reachable:[/] {js.active_ai_label()}")
        raise typer.Exit(1)

    response_text = ""
    try:
        console.print(f"[dim]{js.active_ai_label()}:[/dim] ", end="")
        for chunk in ai_provider.stream(result.optimized_prompt, max_tokens=2048):
            print(chunk, end="", flush=True)
            response_text += chunk
        print()
    except Exception as e:
        err.print(f"[red]AI error:[/] {e}")
        raise typer.Exit(1) from e

    # Self-critique pass (optional, costs 1 extra AI call)
    if self_critique:
        console.print("[dim]Running self-critique pass...[/dim]")
        try:
            corrected = optimizer.self_critique(
                result.optimized_prompt, response_text, result.task_type
            )
            if corrected:
                console.print(
                    "\n[yellow]⚠ Self-critique found issues — "
                    "showing corrected version:[/yellow]\n"
                )
                console.print(corrected)
                response_text = corrected
            else:
                console.print("[green]✓ Self-critique: response looks clean[/green]")
        except Exception as e:
            console.print(f"[dim]Self-critique skipped: {e}[/dim]")

    with contextlib.suppress(Exception):
        optimizer.save_to_history(result, response_text)


# ── tokens ───────────────────────────────────────────────────────────────────

@app.command("tokens", rich_help_panel="⚡  Tools")
def cmd_tokens(
    text: str | None = typer.Argument(None, help="Text to analyze (or use --file / pipe stdin)"),
    file: Path | None = typer.Option(None, "--file", "-f", help="Read from file"),  # noqa: B008
    model: str | None = typer.Option(
        None, "--model", "-m",
        help="Model for budget check (e.g. claude-cli, gpt-4o, llama3.2)",
    ),
    compress: bool = typer.Option(False, "--compress", "-c",
                                  help="Compress the text and show savings"),
    strip_comments: bool = typer.Option(False, "--strip-comments",
                                        help="Also strip code comment lines"),
    no_dedup: bool = typer.Option(False, "--no-dedup",
                                  help="Skip semantic deduplication"),
    target: int | None = typer.Option(None, "--target", "-t",
                                         help="Target token ceiling for compression"),
    verbose: bool = typer.Option(False, "--verbose", "-v",
                                 help="Show per-section token breakdown"),
    repo: str = typer.Option(".", "--repo", "-r"),
) -> None:
    """Count tokens, check model budget, and compress text for AI prompts.

    \b
    Count tokens in text:        jsat tokens "explain the payment service"
    Count tokens in file:        jsat tokens --file README.md
    Check budget against model:  jsat tokens --file context.txt --model gpt-4o
    Compress and show diff:      jsat tokens --file context.txt --compress
    Pipe stdin:                  cat myfile.py | jsat tokens --model claude-cli
    """
    import sys

    from jsat.tools.token_optimizer import TokenOptimizer

    # ── Resolve input ─────────────────────────────────────────────────────────
    if file:
        if not file.exists():
            err.print(f"[red]File not found:[/] {file}")
            raise typer.Exit(1)
        content = file.read_text(encoding="utf-8", errors="replace")
        label = str(file)
    elif text:
        content = text
        label = "<argument>"
    elif not sys.stdin.isatty():
        content = sys.stdin.read()
        label = "<stdin>"
    else:
        err.print("[yellow]Provide text as an argument, --file PATH, or pipe via stdin.[/]")
        err.print("[dim]Example: jsat tokens --file README.md --model gpt-4o[/dim]")
        raise typer.Exit(1)

    _jsat(repo=repo)
    opt = TokenOptimizer(graph=None, cfg=None, ai=None)

    if compress:
        report = opt.compress(content, target_tokens=target, model=model,
                              strip_comments=strip_comments, dedup=not no_dedup)
    else:
        report = opt.analyze(content, model=model)

    # ── Build display table ───────────────────────────────────────────────────
    from rich.panel import Panel
    from rich.table import Table

    t = Table(show_header=False, box=None, padding=(0, 1))
    t.add_column(style="dim", min_width=18)
    t.add_column()

    if label not in ("<argument>", "<stdin>"):
        t.add_row("Source", label)

    if compress and report.savings_tokens > 0:
        t.add_row("Tokens before", f"{report.original_tokens:,}")
        color = "green" if report.savings_pct >= 15 else "yellow"
        t.add_row(
            "Tokens after",
            f"[{color}]{report.compressed_tokens:,}[/]  "
            f"[dim](-{report.savings_tokens:,} tokens, {report.savings_pct:.1f}% saved)[/dim]",
        )
        t.add_row("Strategies", ", ".join(report.strategies_applied) or "none")
    elif compress:
        t.add_row(
            "Tokens", f"{report.original_tokens:,}  [dim](already compact — no savings)[/dim]"
        )
    else:
        t.add_row("Tokens", f"{report.original_tokens:,}")

    if report.model:
        t.add_row("Model", report.model)
    if report.model_limit:
        t.add_row("Context limit", f"{report.model_limit:,}")
    if report.budget_used_pct is not None:
        bpct = report.budget_used_pct
        bar_fill = min(20, int(bpct / 5))
        bar = "[green]" + "█" * bar_fill + "[/green]" + "░" * (20 - bar_fill)
        color = "green" if bpct < 50 else ("yellow" if bpct < 85 else "red")
        t.add_row("Budget used", f"{bar}  [{color}]{bpct:.2f}%[/]")
    if report.elapsed_ms:
        t.add_row("Analysis time", f"{report.elapsed_ms:.1f}ms")

    console.print(Panel(t, title="[bold]Token Analysis[/]", border_style="blue"))

    # ── Section breakdown (--verbose) ─────────────────────────────────────────
    if verbose and report.section_breakdown:
        from rich.table import Table as RTable
        sec = RTable("Section", "Tokens", show_header=True, box=None)
        for k, v in sorted(report.section_breakdown.items(), key=lambda x: -x[1]):
            sec.add_row(k, f"{v:,}")
        console.print(sec)

    # ── Compressed output ─────────────────────────────────────────────────────
    if compress and report.savings_tokens > 0:
        console.print()
        console.rule("[dim]Compressed output[/dim]")
        console.print(report.compressed_text)

# ── knowledge-ingest ──────────────────────────────────────────────────────────

@app.command("knowledge-ingest", rich_help_panel="⚡  Tools")
def cmd_knowledge_ingest(
    path: str = typer.Argument(".", help="Directory or file to ingest"),
    pattern: str = typer.Option("*.md", "--pattern", "-p", help="File glob pattern"),
    category: str = typer.Option("general", "--category", "-c"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be ingested"),
    repo: str = typer.Option(".", "--repo", "-r"),
) -> None:
    """Bulk-ingest markdown files (CLAUDE.md, ADRs, runbooks) into the knowledge base.

    \b
    jsat knowledge-ingest docs/          ingest all .md in docs/
    jsat knowledge-ingest docs/adr/      ingest ADR files
    jsat knowledge-ingest --dry-run .    see what would be ingested
    """
    from jsat.tools.knowledge_ingest import scan_repo
    target = Path(path).resolve()

    if target.is_file():
        from jsat.tools.knowledge_ingest import ingest_markdown
        records = ingest_markdown(target, category=category)
    else:
        records = scan_repo(target)

    if not records:
        console.print("[dim]No files found to ingest.[/dim]")
        return

    console.print(f"\nFound [bold]{len(records)}[/] entries to ingest from [cyan]{target}[/]\n")
    for r in records[:10]:
        console.print(f"  [dim]{r.category:15}[/] {r.source_file.name}: {r.text[:60]}...")
    if len(records) > 10:
        console.print(f"  [dim]... and {len(records)-10} more[/dim]")

    if dry_run:
        console.print("\n[dim][dry-run] Not ingesting.[/dim]")
        return

    js = _jsat(repo=repo)
    from jsat.tools.knowledge import KnowledgeTool
    tool = KnowledgeTool(graph=js._get_graph(), cfg=js._cfg, ai=js._get_ai())
    ingested = 0
    for r in records:
        try:
            tool.add(r.text, category=r.category)
            ingested += 1
        except Exception as e:
            err.print(f"[yellow]Skip {r.source_file.name}:[/] {e}")

    console.print(f"\n[green]✓[/] Ingested [bold]{ingested}[/] entries into knowledge base.")
