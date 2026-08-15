"""jsat._cli_improve — the `jsat improve` command (self-improvement)."""
from __future__ import annotations

import typer

from ._cli_common import _jsat, app, console, err


@app.command("improve", rich_help_panel="⚡  Tools")
def cmd_improve(
    list_only: bool = typer.Option(False, "--list", "-l",
        help="Show recorded issues without analysing anything"),
    cluster_id: str = typer.Option("", "--id",
        help="Work on a specific issue id (from --list)"),
    report: bool = typer.Option(False, "--report",
        help="Open a pre-filled GitHub issue in your browser"),
    dry_run: bool = typer.Option(False, "--dry-run",
        help="With --report, print the URL instead of opening a browser"),
    submit: str = typer.Option("", "--submit",
        help="MAINTAINER ONLY: apply a bundle in a JSAT checkout and open a PR"),
    repo: str = typer.Option(".", "--repo", "-r"),
) -> None:
    """Diagnose problems JSAT hit in itself and propose a fix.

    JSAT records friction it encounters in its own code — crashes, capability
    gaps, bad errors, timeouts. This command asks your configured AI provider to
    diagnose the most frequent one and draft a patch to JSAT's own source.

    \b
    Only JSAT-internal data is ever recorded — no code, paths, or identifiers
    from your project. Nothing is sent anywhere unless you run --report, which
    opens a pre-filled issue for you to review and submit yourself.
    JSAT never modifies its own installed files.

    \b
    jsat improve --list             show what has been recorded
    jsat improve                    diagnose the top issue, write a bundle
    jsat improve --report           open a pre-filled GitHub issue
    jsat improve --id a1b2c3d4      work on one specific issue

    \b
    Disable capture entirely:
      export JSAT_NO_IMPROVE=1      or set improve.enabled: false in config
    """
    from jsat._improve import suppress_nudge
    from jsat.tools import improve as improve_tool

    suppress_nudge()  # this command reports the issues itself

    if submit:
        from jsat.tools.improve_submit import submit_bundle
        submit_bundle(submit, repo=repo)
        return

    clusters = improve_tool.list_clusters()
    if list_only or not clusters:
        _print_clusters(clusters)
        return

    target = improve_tool.select_target(cluster_id or None)
    if target is None:
        if cluster_id:
            err.print(f"[red]No recorded issue matching id:[/] {cluster_id}")
            raise typer.Exit(1)
        console.print("[green]✓[/] Nothing new to improve — all recorded issues are reported.")
        return

    js = _jsat(repo=repo)
    ai = js._get_ai()
    label = f"{target.get('exc_type') or target.get('kind')} (x{target.get('count')})"
    console.print(f"[dim]Diagnosing[/] {label} [dim]with {js.active_ai_label()}…[/]")

    analysis, diff, status, changed = improve_tool.diagnose(target, ai)

    bundle = improve_tool.write_bundle(
        target, analysis, diff, status, changed,
        provider=js._cfg.ai.provider, model=js._cfg.ai.model,
    )
    improve_tool.mark_reported(target["fingerprint"], bundle.name)

    _print_status(status, changed)
    console.print(f"\n[bold]Bundle:[/] [cyan]{bundle}[/]")

    if report:
        _open_report(target, bundle, js._cfg.improve.github_repo, dry_run=dry_run)
    else:
        console.print("\nShare it: [bold]jsat improve --report[/]")


def _print_clusters(clusters: list) -> None:
    from rich import box
    from rich.table import Table

    if not clusters:
        console.print(
            "[green]✓[/] No issues recorded — JSAT has not hit any friction on this machine.\n"
            "[dim]Capture is local-only and JSAT-internal-only; "
            "disable with JSAT_NO_IMPROVE=1.[/]"
        )
        return

    table = Table(box=box.SIMPLE, title="Recorded JSAT issues")
    for column in ("id", "kind", "issue", "where", "count", "last seen", "reported"):
        table.add_column(column)
    for cluster in clusters[:25]:
        table.add_row(
            cluster["fingerprint"][:8],
            str(cluster.get("kind", "")),
            str(cluster.get("exc_type") or cluster.get("message_class") or "—"),
            str(cluster.get("op") or "—"),
            str(cluster.get("count", 0)),
            str(cluster.get("last_seen", ""))[:16],
            "✓" if cluster.get("reported") else "",
        )
    console.print(table)

    from jsat._improve import read_state
    dropped = read_state().get("dropped_count", 0)
    if dropped:
        console.print(f"[dim]{dropped} signal(s) dropped by the privacy filter.[/]")
    console.print("Analyse the top issue: [bold]jsat improve[/]")


def _print_status(status: str, changed: list) -> None:
    messages = {
        "validated": ("green", f"✓ Patch validated against {len(changed)} file(s): "
                               f"{', '.join(changed)}"),
        "did_not_apply": ("yellow", "⚠ Patch did not apply cleanly — included raw "
                                    "for the maintainer"),
        "no_patch": ("yellow", "⚠ The model returned no usable diff — diagnosis only"),
        "ai_error": ("yellow", "⚠ AI call failed — diagnosis-only bundle written"),
        "no_ai": ("yellow", "⚠ No AI provider reachable — diagnosis-only bundle written.\n"
                            "  Configure one: [bold]jsat ai use claude_cli[/]"),
    }
    colour, text = messages.get(status, ("dim", status))
    console.print(f"[{colour}]{text}[/]")


def _open_report(target: dict, bundle, github_repo: str, *, dry_run: bool) -> None:
    import webbrowser

    from jsat.tools import improve as improve_tool

    body = (bundle / "issue.md").read_text(encoding="utf-8")
    # NOTE: never interpolate the bundle path here — it is an absolute local path
    # containing the username/home dir, and this body is published to GitHub.
    body += "\n\n_A `patch.diff` accompanies this report; attach it from the bundle " \
            "directory printed by `jsat improve`._\n"

    from jsat._improve._sanitize import verify_clean
    if not verify_clean(body):
        err.print(
            "[red]Refusing to open the report:[/] the issue body did not pass the "
            "privacy filter.\nInspect it yourself at: "
            f"[cyan]{bundle / 'issue.md'}[/]"
        )
        raise typer.Exit(1)

    url = improve_tool.issue_url(github_repo, target, body)

    console.print(
        "\n[bold yellow]Review before submitting.[/] "
        "The issue opens pre-filled in your browser — nothing is sent until you "
        "press Submit."
    )
    console.print(f"[dim]{url}[/]")
    if dry_run:
        return
    try:
        if not webbrowser.open(url):
            console.print("[dim]Could not open a browser — copy the URL above.[/]")
    except Exception:
        console.print("[dim]Could not open a browser — copy the URL above.[/]")
