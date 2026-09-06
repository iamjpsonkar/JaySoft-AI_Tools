"""jsat._cli_session — `jsat session` (resumable work) and `jsat note` (quick notes)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import typer

from ._cli_common import _jsat, app, console, err

session_app = typer.Typer(
    help=(
        "Inspect and resume JSAT skill sessions.\n\n"
        "Long-running skills (magic, crack, sprint, prompt) write a session file "
        "as they go, so an interrupted run can pick up where it left off."
    ),
    rich_markup_mode="rich",
)
note_app = typer.Typer(
    help=(
        "Quick notes, stored in the JSAT knowledge base.\n\n"
        "Notes are knowledge entries with category 'note', so they are searchable "
        "alongside ADRs and runbooks and are visible to every AI tool via MCP."
    ),
    rich_markup_mode="rich",
)
plan_app = typer.Typer(
    help=(
        "Propose-then-approve plans for any JSAT call.\n\n"
        "An AI that passes mode=plan to an MCP tool gets a plan back and executes "
        "nothing; approve it here (or via execute_plan) to run every step."
    ),
    rich_markup_mode="rich",
)
app.add_typer(session_app, name="session", rich_help_panel="⚡  Tools")
app.add_typer(note_app, name="note", rich_help_panel="⚡  Tools")
app.add_typer(plan_app, name="plan", rich_help_panel="⚡  Tools")


# ── sessions ──────────────────────────────────────────────────────────────────

@session_app.command("list")
def cmd_session_list(
    skill: str = typer.Option("", "--skill", "-s", help="Filter by skill (magic, crack…)"),
    status: str = typer.Option("", "--status", help="in_progress | completed | abandoned"),
    limit: int = typer.Option(20, "--limit", "-n"),
) -> None:
    """List recent skill sessions, newest first."""
    from rich import box
    from rich.table import Table

    from jsat import _sessions

    found = _sessions.list_sessions(skill=skill or None, status=status or None, limit=limit)
    if not found:
        console.print(
            "[dim]No sessions yet.[/] They are created by long-running skills — "
            "try [bold]/jsat magic <task>[/] in Claude Code."
        )
        return

    table = Table(box=box.SIMPLE, title="JSAT sessions")
    for col in ("skill", "task", "progress", "status", "file"):
        table.add_column(col)
    for s in found:
        progress = f"{s.done_count}/{len(s.steps)}" if s.steps else "—"
        colour = {"in_progress": "yellow", "completed": "green"}.get(s.status, "dim")
        table.add_row(
            s.skill, s.task[:44] or "—", progress,
            f"[{colour}]{s.status}[/]", s.path.name,
        )
    console.print(table)

    resumable = [s for s in found if s.status == "in_progress"]
    if resumable:
        console.print(
            f"Resume the newest: [bold]jsat session resume[/]  "
            f"[dim]({resumable[0].path.name})[/]"
        )


@session_app.command("show")
def cmd_session_show(
    name: str = typer.Argument("", help="Session filename or fragment (default: newest)"),
) -> None:
    """Show one session — steps, findings, and where it stopped."""
    session = _resolve_session(name)
    console.print(f"[bold]{session.skill}[/] — {session.task}")
    console.print(f"[dim]{session.path}[/]")
    console.print(f"Status: {session.status}   Created: {session.created}\n")

    for step in session.steps:
        mark = "[green]✓[/]" if step.done else "[dim]○[/]"
        detail = f" [dim]{step.finding}[/]" if step.finding else ""
        console.print(f"  {mark} {step.name}{detail}")

    if session.findings:
        console.print("\n[bold]Findings[/]")
        for line in session.findings:
            console.print(f"  {line}")


@session_app.command("resume")
def cmd_session_resume(
    name: str = typer.Argument("", help="Session filename or fragment (default: newest)"),
) -> None:
    """Show exactly where a session stopped, and how to continue it."""
    _do_resume(name)


@session_app.command("continue")
def cmd_session_continue(
    name: str = typer.Argument("", help="Session filename or fragment (default: newest)"),
) -> None:
    """Resume a saved session — alias for `resume`, with a CLI resume hint."""
    _do_resume(name)


def _do_resume(name: str) -> None:
    session = _resolve_session(name, status="in_progress")
    step = session.next_step
    if step is None:
        console.print("[green]✓[/] Nothing left to do — every step is complete.")
        return

    console.print(f"[bold]Resuming[/] {session.skill}: {session.task}")
    console.print(f"[dim]{session.path}[/]")
    console.print(f"Completed {session.done_count}/{len(session.steps)} steps.")
    console.print(f"\nNext step: [bold]{step.name}[/]")
    if session.findings:
        console.print("\n[dim]Context carried forward:[/]")
        for line in session.findings[-5:]:
            console.print(f"  {line}")
    if session.skill == "session":
        console.print(f"\nResume later: [bold]jsat session continue {session.path.name}[/]")
    else:
        console.print(f"\nIn Claude Code run: [bold]/jsat {session.skill} --continue[/]")


@session_app.command("rm")
def cmd_session_rm(
    name: str = typer.Argument(..., help="Session filename or fragment"),
) -> None:
    """Delete one session file."""
    session = _resolve_session(name)
    session.path.unlink()
    console.print(f"[green]✓[/] Removed {session.path.name}")


@session_app.command("prune")
def cmd_session_prune(
    keep: int = typer.Option(50, "--keep", "-k", help="How many recent sessions to keep"),
    all_: bool = typer.Option(False, "--all", help="Also prune unfinished sessions"),
) -> None:
    """Delete old session files (unfinished ones are kept unless --all)."""
    from jsat import _sessions

    removed = _sessions.prune(keep=keep, completed_only=not all_)
    console.print(f"[green]✓[/] Removed {removed} session file(s); kept the newest {keep}.")


# ── save / continue — capture working context from anywhere ──────────────────


@session_app.command("save")
def cmd_session_save(
    task: str = typer.Argument(..., help="What you are in the middle of"),
    skill: str = typer.Option("session", "--skill", "-s",
        help="Group under this label (default: 'session')"),
    status: str = typer.Option("in_progress", "--status", "-S",
        help="in_progress | completed | abandoned | proposed | rejected"),
    step: list[str] = typer.Option(None, "--step", "-p",  # noqa: B008
        help="A step to plan (repeatable; default: one 'Execute the task')"),
    finding: list[str] = typer.Option(None, "--finding", "-f",  # noqa: B008
        help="A finding / context note (repeatable)"),
    no_context: bool = typer.Option(False, "--no-context",
        help="Skip auto-capturing the repo/git context"),
    repo: str = typer.Option(".", "--repo", "-r"),
) -> None:
    """Save the current working context as a resumable session.

    \b
    jsat session save "add idempotency keys to payments" \\
        --step "find all payment mutations" --step "check the retry path"
    jsat session save "debug the checkout 500" --no-context

    Unlike skill-run sessions this works from anywhere — no /jsat skill
    involved. The file lands in ~/.jsat/sessions/ in the same format the
    skills use, so `jsat session list/show/continue/prune` all read it, and
    repo path + git branch/commit are captured as context unless --no-context.
    """
    from jsat import _sessions

    status = status or "in_progress"
    if status not in _sessions.SCHEMA_STATUSES:
        err.print(
            f"[red]Invalid status '[/]{status}[red]'[/] — expected one of: "
            f"{', '.join(_sessions.SCHEMA_STATUSES)}"
        )
        raise typer.Exit(1)
    task = task.strip()
    if not task:
        err.print("[red]A task description is required.[/]")
        raise typer.Exit(1)

    steps = list(step) if step else ["Execute the task"]
    session = _sessions.create(skill=skill or "session", task=task, steps=steps)
    if not no_context:
        session.findings.extend(_context_findings(repo))
    if finding:
        session.findings.extend(
            f"**note:** {f.strip()}" for f in finding if f.strip()
        )
    session.save()

    console.print(f"[green]✓[/] Session saved: [bold]{session.path.name}[/]")
    console.print(f"[dim]{session.skill}[/]: {session.task}")
    console.print(
        f"  {session.done_count}/{len(session.steps)} step(s) planned "
        f"· status: {session.status}"
    )
    console.print(
        f"Continue later: [bold]jsat session continue {session.path.name}[/]"
    )


def _context_findings(repo: str) -> list[str]:
    """Best-effort ambient context — resolved repo path, then git branch + commit."""
    root = Path(repo).expanduser().resolve()
    findings = [f"**context:** repo={root}"]
    try:
        branch = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        if branch.returncode == 0 and branch.stdout.strip():
            line = f"**context:** branch={branch.stdout.strip()}"
            sha = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, timeout=10,
            )
            if sha.returncode == 0 and sha.stdout.strip():
                line += f" commit={sha.stdout.strip()}"
            findings.append(line)
    except Exception:
        pass
    return findings


def _resolve_session(name: str, status: str | None = None):
    """Find a session by filename fragment, else the newest (optionally filtered)."""
    from jsat import _sessions

    if name:
        for session in _sessions.list_sessions(limit=500):
            if name in session.path.name:
                return session
        err.print(f"[red]No session matching:[/] {name}")
        raise typer.Exit(1)

    session = _sessions.latest(status=status) if status else None
    if session is None:
        found = _sessions.list_sessions(status=status, limit=1)
        session = found[0] if found else None
    if session is None:
        err.print(
            "[red]No matching session found.[/] "
            "Run [bold]jsat session list[/] to see what exists."
        )
        raise typer.Exit(1)
    return session


# ── notes ─────────────────────────────────────────────────────────────────────

_NOTE_CATEGORY = "note"


@note_app.command("add")
def cmd_note_add(
    text: str = typer.Argument(..., help="The note text"),
    category: str = typer.Option(_NOTE_CATEGORY, "--category", "-c",
        help="note | adr | runbook | pattern | decision"),
    repo: str = typer.Option(".", "--repo", "-r"),
) -> None:
    """Save a note into the knowledge base.

    \b
    jsat note add "retry uses tenacity, see ADR-007"
    jsat note add -c adr "all payment mutations need idempotency keys"

    Notes are stored as knowledge entries, so they are searchable with
    `jsat note search`, `jsat knowledge search`, and from any AI tool via MCP.
    """
    tool = _knowledge_tool(repo)
    tool.add(text, category=category)
    console.print(f"[green]✓[/] Saved as [bold]{category}[/]: {text[:70]}")
    console.print("[dim]Find it later: jsat note search <words>[/]")


@note_app.command("list")
def cmd_note_list(
    category: str = typer.Option(_NOTE_CATEGORY, "--category", "-c",
        help="Category to list; use 'all' for everything"),
    limit: int = typer.Option(20, "--limit", "-n"),
    repo: str = typer.Option(".", "--repo", "-r"),
) -> None:
    """List saved notes, newest first."""
    tool = _knowledge_tool(repo)
    entries = tool.list_entries(category=None if category == "all" else category)
    _print_entries(entries, limit, empty_hint='jsat note add "your first note"')


@note_app.command("search")
def cmd_note_search(
    query: str = typer.Argument(..., help="Words to search for"),
    limit: int = typer.Option(10, "--limit", "-n"),
    repo: str = typer.Option(".", "--repo", "-r"),
) -> None:
    """Search notes and every other knowledge entry."""
    tool = _knowledge_tool(repo)
    result = tool.query(query)
    entries = getattr(result, "entries", None) or getattr(result, "results", None) or []
    if not entries:
        console.print(f"[dim]Nothing found for:[/] {query}")
        return
    _print_entries(entries, limit, empty_hint="")
    answer = getattr(result, "answer", "")
    if answer:
        console.print(f"\n{answer}")


def _knowledge_tool(repo: str):
    from jsat.tools.knowledge import KnowledgeTool

    js = _jsat(repo=repo)
    return KnowledgeTool(graph=js._get_graph(), cfg=js._cfg, ai=js._get_ai())


def _print_entries(entries: list, limit: int, empty_hint: str) -> None:
    from rich import box
    from rich.table import Table

    if not entries:
        hint = f" Try: [bold]{empty_hint}[/]" if empty_hint else ""
        console.print("[dim]No entries yet.[/]" + hint)
        return

    table = Table(box=box.SIMPLE)
    for col in ("id", "category", "note", "created"):
        table.add_column(col)
    for entry in entries[:limit]:
        props = entry.get("properties", entry) if isinstance(entry, dict) else {}
        entry_id = str(props.get("id") or entry.get("id", ""))[-8:]
        table.add_row(
            entry_id,
            str(props.get("category", "")),
            str(props.get("text", ""))[:70],
            str(props.get("created_at", ""))[:16],
        )
    console.print(table)
    if len(entries) > limit:
        console.print(f"[dim]…and {len(entries) - limit} more (use --limit).[/]")


# ── plans (mode=plan proposals) ───────────────────────────────────────────────

@plan_app.command("list")
def cmd_plan_list(
    status: str = typer.Option("", "--status",
        help="proposed | in_progress | completed | rejected"),
) -> None:
    """List plans an AI drafted with mode=plan (nothing ran yet)."""
    from rich import box
    from rich.table import Table

    from jsat import _planner

    plans = _planner.list_plans()
    if status:
        plans = [p for p in plans if p.status == status]
    if not plans:
        console.print(
            "[dim]No plans yet.[/] An AI drafts one when it calls an MCP tool "
            "with mode=plan — zero execution until you approve."
        )
        return

    table = Table(box=box.SIMPLE, title="JSAT plans")
    for col in ("id", "steps", "status", "file"):
        table.add_column(col)
    colour = {"proposed": "yellow", "in_progress": "yellow",
              "completed": "green", "rejected": "dim"}
    for s in plans:
        table.add_row(
            s.path.stem,
            f"{s.done_count}/{len(s.steps)}",
            f"[{colour.get(s.status, 'dim')}]{s.status}[/]",
            s.path.name,
        )
    console.print(table)
    console.print(
        "Approve + run: [bold]jsat plan run <id>[/]   Review: [bold]jsat plan show <id>[/]"
    )


@plan_app.command("show")
def cmd_plan_show(
    name: str = typer.Argument(..., help="Plan id (filename stem or fragment)"),
) -> None:
    """Show one plan — its steps, kinds, and current status."""
    from jsat import _planner

    session = _resolve_plan(name)
    meta = {m["name"]: m for m in _planner._read_meta(session).get("steps", [])}

    console.print(f"[bold]{session.path.stem}[/]  ({session.status})")
    console.print(f"[dim]{session.task}[/]")
    console.print(f"[dim]{session.path}[/]\n")

    if session.status == "proposed":
        console.print("[yellow]Nothing has been executed.[/]\n")

    for i, step in enumerate(session.steps, start=1):
        m = meta.get(step.name, {})
        kind = m.get("kind", "")
        mark = "[green]✓[/]" if step.done else "[dim]○[/]"
        detail = f" [dim]{step.finding}[/]" if step.finding else ""
        console.print(f"  {mark} {i}. {step.name}  ([dim]{kind}[/]){detail}")

    if session.status == "proposed":
        console.print(f"\nApprove + run: [bold]jsat plan run {session.path.stem}[/]")


@plan_app.command("approve")
def cmd_plan_approve(
    name: str = typer.Argument(..., help="Plan id (filename stem or fragment)"),
) -> None:
    """Mark a proposed plan as approved (ready to run)."""
    session = _resolve_plan(name)
    if session.status == "completed":
        console.print("[yellow]Already completed — nothing to approve.[/]")
        raise typer.Exit(0)
    session.status = "in_progress"
    session.save()
    console.print(f"[green]✓[/] Approved {session.path.stem}. Run it: [bold]jsat plan run "
                  f"{session.path.stem}[/]")


@plan_app.command("run")
def cmd_plan_run(
    name: str = typer.Argument(..., help="Plan id (filename stem or fragment)"),
    repo: str = typer.Option(".", "--repo", "-r"),
) -> None:
    """Execute every pending step of an approved plan."""
    from rich import box
    from rich.table import Table

    from jsat import _planner

    session = _resolve_plan(name)
    if session.status == "completed":
        console.print("[yellow]Already completed.[/] See: [bold]jsat plan show "
                      f"{session.path.stem}[/]")
        raise typer.Exit(0)

    js = _jsat(repo=repo)
    server = _plan_server(js)

    def dispatch(tool: str, tool_args: dict) -> object:
        return server._call(tool, dict(tool_args))

    def step_cb(pos: int, total: int) -> None:
        console.print(f"  [dim]step {pos}/{total}…[/]")

    console.print(f"[bold]Executing[/] {session.path.stem}\n")
    outcome = _planner.execute_plan(session, dispatch, step_callback=step_cb)

    table = Table(box=box.SIMPLE, title="Plan result")
    for col in ("#", "tool", "kind", "ok", "result"):
        table.add_column(col)
    for r in outcome["results"]:
        table.add_row(str(r["step"]), r["tool"], r["kind"],
                      "[green]ok[/]" if r["ok"] else "[red]FAIL[/]",
                      r["result"][:80])
    console.print(table)
    if outcome["errors"]:
        console.print(f"[red]{outcome['errors']} step(s) failed[/] — recorded in the "
                      "session findings. Fix and retry with: [bold]jsat plan run "
                      f"{session.path.stem}[/]")
    else:
        console.print(f"[green]✓[/] All {outcome['steps_run']} step(s) executed.")


@plan_app.command("discard")
def cmd_plan_discard(
    name: str = typer.Argument(..., help="Plan id (filename stem or fragment)"),
) -> None:
    """Reject a plan without executing it."""
    session = _resolve_plan(name)
    if session.status == "completed":
        console.print("[yellow]Already completed — discard refused.[/]")
        raise typer.Exit(0)
    session.status = "rejected"
    session.save()
    console.print(f"[dim]-[/] Rejected {session.path.stem}.")


def _resolve_plan(name: str):
    from jsat import _planner

    session = _planner.load_plan(name) if name else None
    if session is not None:
        return session
    err.print(f"[red]No plan matching:[/] {name}")
    raise typer.Exit(1)


def _plan_server(js) -> object:
    """A real MCPServer to dispatch plan steps through (budgets, depth, RBAC)."""
    from jsat.mcp.server import MCPServer

    return MCPServer(js)
