"""
jsat._cli_analysis — analysis commands used by CI: blast-radius,
contract-check, security-review.

These three existed as MCP tools and as slash commands but not as CLI
commands, while `jsat ci-setup` generated a pipeline that invoked them by
name — so anyone who followed the generated workflow got a failing build.
The flags here match that template exactly (`--diff`, `--output`, `--base`,
`--sarif`), because the template is the contract.

Each command exits non-zero when it finds something CI should block on, so
the pipeline step fails loudly rather than passing with findings in the log.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from ._cli_common import _jsat, app, console, err

# ── SARIF ─────────────────────────────────────────────────────────────────────

_SARIF_LEVEL = {
    "critical": "error",
    "high": "error",
    "medium": "warning",
    "low": "note",
    "info": "note",
}


def _sarif_document(findings: list[Any], repo: Path) -> dict[str, Any]:
    """Build a SARIF 2.1.0 document from SecurityFinding records.

    Written by hand rather than pulling in sarif-tools: the subset GitHub's
    upload-sarif action and GitLab's SAST report reader need is small and
    stable, and a hard dependency here would push `jsat[ci]` onto every user
    who only wants the console output.
    """
    rules: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    for f in findings:
        rule_id = getattr(f, "rule_id", None) or "jsat.finding"
        if rule_id not in rules:
            rules[rule_id] = {
                "id": rule_id,
                "name": rule_id,
                "shortDescription": {"text": getattr(f, "title", rule_id)},
                "fullDescription": {
                    "text": getattr(f, "description", "") or getattr(f, "title", "")
                },
                "help": {"text": getattr(f, "remediation", "") or ""},
                "properties": {
                    "category": getattr(f, "category", "security"),
                    "severity": getattr(f, "severity", "medium"),
                },
            }
        raw_file = str(getattr(f, "file", "") or "")
        try:
            uri = str(Path(raw_file).resolve().relative_to(repo.resolve()))
        except (ValueError, OSError):
            uri = raw_file
        results.append({
            "ruleId": rule_id,
            "level": _SARIF_LEVEL.get(str(getattr(f, "severity", "")).lower(),
                                      "warning"),
            "message": {"text": getattr(f, "title", "") or rule_id},
            "locations": [{
                "physicalLocation": {
                    "artifactLocation": {"uri": uri},
                    "region": {"startLine": max(1, int(getattr(f, "line", 1) or 1))},
                }
            }],
        })
    return {
        "$schema": ("https://raw.githubusercontent.com/oasis-tcs/sarif-spec/"
                    "master/Schemata/sarif-schema-2.1.0.json"),
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {
                "name": "JSAT",
                "informationUri": "https://github.com/iamjpsonkar/JaySoft-AI_Tools",
                "rules": list(rules.values()),
            }},
            "results": results,
        }],
    }


# ── blast-radius ──────────────────────────────────────────────────────────────

@app.command("blast-radius", rich_help_panel="⚡  Tools")
def cmd_blast_radius(
    target: str | None = typer.Argument(
        None, help="Symbol, file, or node id to trace. Omit when using --diff."),
    diff: str | None = typer.Option(
        None, "--diff", "-d",
        help="Git range (e.g. origin/main...HEAD) or a unified diff file"),
    max_depth: int = typer.Option(5, "--max-depth", help="Traversal depth"),
    output: str | None = typer.Option(
        None, "--output", "-o", help="Write a Markdown report to this file"),
    fail_on_breaking: bool = typer.Option(
        False, "--fail-on-breaking",
        help="Exit non-zero if any breaking impact is found"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON to stdout"),
    repo: str = typer.Option(".", "--repo", "-r"),
) -> None:
    """Trace the downstream impact of a change.

    \b
    jsat blast-radius process_payment
    jsat blast-radius --diff origin/main...HEAD --output blast-radius.md
    """
    if not target and not diff:
        err.print("[bold red]Provide a target, or --diff.[/]")
        raise typer.Exit(2)

    js = _jsat(repo=repo)
    diff_text = diff
    if diff:
        candidate = Path(diff)
        if candidate.is_file():
            diff_text = candidate.read_text(encoding="utf-8", errors="replace")

    try:
        report = js.blast_radius(target=target or "", diff=diff_text,
                                 max_depth=max_depth)
    except Exception as e:
        err.print(f"[bold red]Blast radius failed:[/] {e}")
        raise typer.Exit(1) from e

    impacts = list(getattr(report, "impacts", []) or [])
    summary = getattr(report, "summary", {}) or {}
    breaking = int(summary.get("breaking", 0) or 0)

    if json_out:
        console.print_json(json.dumps(_dump(report)))
    else:
        label = getattr(report, "target", "") or (f"diff {diff}" if diff else "?")
        console.print(
            f"\n[bold]Blast radius:[/] {label}\n"
            f"  impacted: {len(impacts)}   "
            f"breaking: {breaking}   "
            f"degraded: {summary.get('degraded', 0)}   "
            f"warning: {summary.get('warning', 0)}   "
            f"safe: {summary.get('safe', 0)}"
        )
        for item in impacts[:25]:
            console.print(f"  [{item.severity}] {item.node_name}  "
                          f"[dim]{item.file}[/]")
        if len(impacts) > 25:
            console.print(f"  [dim]… and {len(impacts) - 25} more[/]")

    if output:
        Path(output).write_text(_blast_markdown(report), encoding="utf-8")
        console.print(f"[green]✓[/] Report written to [bold]{output}[/]")

    if fail_on_breaking and breaking:
        err.print(f"[bold red]{breaking} breaking impact(s) found.[/]")
        raise typer.Exit(1)


def _blast_markdown(report: Any) -> str:
    summary = getattr(report, "summary", {}) or {}
    lines = [
        f"# Blast radius — `{getattr(report, 'target', '') or 'diff'}`",
        "",
        "| Severity | Count |",
        "|---|---|",
    ]
    for key in ("breaking", "degraded", "warning", "safe"):
        lines.append(f"| {key} | {summary.get(key, 0)} |")
    impacts = list(getattr(report, "impacts", []) or [])
    if impacts:
        lines += ["", "## Impacted", "",
                  "| Severity | Symbol | File | Depth | Reason |",
                  "|---|---|---|---|---|"]
        for i in impacts:
            lines.append(
                f"| {i.severity} | `{i.node_name}` | `{i.file}` | {i.depth} "
                f"| {i.reason or ''} |")
    diagram = getattr(report, "mermaid_diagram", "")
    if diagram:
        lines += ["", "## Graph", "", "```mermaid", diagram, "```"]
    return "\n".join(lines) + "\n"


# ── contract-check ────────────────────────────────────────────────────────────

@app.command("contract-check", rich_help_panel="⚡  Tools")
def cmd_contract_check(
    base: str = typer.Option("origin/main", "--base", "-b",
                             help="Base git ref to compare from"),
    head: str = typer.Option("HEAD", "--head", help="Head git ref to compare to"),
    fail_on_breaking: bool = typer.Option(
        True, "--fail-on-breaking/--no-fail-on-breaking",
        help="Exit non-zero when a breaking API change is detected"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON to stdout"),
    repo: str = typer.Option(".", "--repo", "-r"),
) -> None:
    """Check API contract compatibility between two git refs.

    \b
    jsat contract-check --base origin/main
    jsat contract-check --base v1 --head v2 --json
    """
    js = _jsat(repo=repo)
    try:
        from jsat.tools.contract import ContractTool
        tool = ContractTool(graph=js._get_graph(), cfg=js._cfg)
        report = tool.run(base=base, head=head)
    except Exception as e:
        err.print(f"[bold red]Contract check failed:[/] {e}")
        raise typer.Exit(1) from e

    changes = list(getattr(report, "changes", []) or [])
    # ContractReport already counts these; recomputing from a guessed field
    # name is how --fail-on-breaking silently stops working.
    breaking_count = int(getattr(report, "breaking_count", 0) or 0)
    score = getattr(report, "compat_score", None)

    if json_out:
        console.print_json(json.dumps(_dump(report)))
    else:
        console.print(
            f"\n[bold]API contract[/] {base} → {head}\n"
            f"  changes: {len(changes)}   breaking: {breaking_count}"
            + (f"   compatibility: {score:.0f}%" if isinstance(score, (int, float))
               else "")
        )
        for c in changes[:25]:
            mark = "[red]BREAKING[/]" if c.get("is_breaking") else "[dim]ok[/]"
            kind = c.get("change_type", "changed")
            what = (c.get("content") or "").strip()[:80]
            spec = c.get("spec", "")
            reason = c.get("reason", "")
            console.print(f"  {mark} {kind}: {what}"
                          + (f"  [dim]({spec})[/]" if spec else "")
                          + (f"\n      [dim]{reason}[/]" if reason else ""))
        if len(changes) > 25:
            console.print(f"  [dim]… and {len(changes) - 25} more[/]")
        guide = getattr(report, "migration_guide", "")
        if guide:
            console.print(f"\n[bold]Migration guide[/]\n{guide}")

    if fail_on_breaking and breaking_count:
        err.print(f"[bold red]{breaking_count} breaking API change(s).[/]")
        raise typer.Exit(1)


# ── security-review ───────────────────────────────────────────────────────────

@app.command("security-review", rich_help_panel="⚡  Tools")
def cmd_security_review(
    path: str = typer.Argument(".", help="File or directory to scan"),
    severity: str = typer.Option(
        "medium", "--severity", "-s",
        help="Minimum severity: critical | high | medium | low"),
    sarif: str | None = typer.Option(
        None, "--sarif", help="Write a SARIF 2.1.0 report to this file"),
    no_deps: bool = typer.Option(False, "--no-deps",
                                 help="Skip the dependency CVE lookup"),
    fail_on_critical: bool = typer.Option(
        False, "--fail-on-critical",
        help="Exit non-zero if any critical finding is present"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON to stdout"),
    repo: str = typer.Option(".", "--repo", "-r"),
) -> None:
    """Run an OWASP scan, secret detection, and a dependency CVE lookup.

    \b
    jsat security-review .
    jsat security-review . --sarif security.sarif
    jsat security-review svc/config.py --severity low
    """
    js = _jsat(repo=repo)
    try:
        report = js.security_review(path=path, severity_threshold=severity,
                                    include_deps=not no_deps)
    except Exception as e:
        err.print(f"[bold red]Security review failed:[/] {e}")
        raise typer.Exit(1) from e

    findings = list(getattr(report, "findings", []) or [])
    cves = list(getattr(report, "cves", []) or [])
    secrets = int(getattr(report, "secrets_found", 0) or 0)
    critical = [f for f in findings
                if str(getattr(f, "severity", "")).lower() == "critical"]

    if json_out:
        console.print_json(json.dumps(_dump(report)))
    else:
        console.print(
            f"\n[bold]Security review:[/] {path}\n"
            f"  findings: {len(findings)}   secrets: {secrets}   "
            f"CVEs: {len(cves)}   critical: {len(critical)}"
        )
        for f in findings[:25]:
            console.print(f"  [{f.severity}] {f.title}  [dim]{f.file}:{f.line}[/]")
        if len(findings) > 25:
            console.print(f"  [dim]… and {len(findings) - 25} more[/]")

    if sarif:
        doc = _sarif_document(findings, Path(repo))
        Path(sarif).write_text(json.dumps(doc, indent=2), encoding="utf-8")
        console.print(f"[green]✓[/] SARIF written to [bold]{sarif}[/] "
                      f"({len(doc['runs'][0]['results'])} result(s))")

    if fail_on_critical and critical:
        err.print(f"[bold red]{len(critical)} critical finding(s).[/]")
        raise typer.Exit(1)


def _dump(obj: Any) -> Any:
    """Best-effort JSON view of a result model.

    Handles both shapes in use: pydantic models (blast radius, security) and
    plain dataclasses (ContractReport).
    """
    import dataclasses
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    return str(obj)
