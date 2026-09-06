"""
JSAT self-test — no-mocking, end-to-end verification of the INSTALLED jsat.

Every check exercises the real artifact: the real console script as a
subprocess, the real MCP server over real stdio JSON-RPC, the real connector
files on disk, the real graph backends, real external services when they are
reachable. Nothing is stubbed or monkeypatched. The only substitution made
anywhere is a recorder stub standing in for a *third-party* binary that JSAT
launches (claude/codex/...), because the thing under test there is the argv
and config JSAT produces, not the other tool.

A check whose external dependency is absent is reported `unavailable` — never
a false failure, and never silently skipped.

The default run executes suites concurrently: each suite runs in its own
subprocess with a private workspace (its own JSAT_DATA_DIR / SESSIONS /
IMPROVE / RUNTIME) under a shared tempdir, and the parent merges the per-suite
reports in SUITES order, so the report is deterministic even though the wall
time is roughly `max(suite)` instead of `sum(suite)`. The `environment` suite,
the fixture-repo build and the final state-leak check always run on the parent.
`--sequential` restores the pre-parallel in-process one-suite-at-a-time run.

Usage:
  python3 -m selftest                      # everything available, no LLM cost
  python3 -m selftest --llm                # also drive real AI provider calls
  python3 -m selftest --live-agent         # also drive real `claude -p` skills
  python3 -m selftest --suite mcp,cli      # just these suites
  python3 -m selftest --list-suites
  python3 -m selftest --out /tmp/report
  python3 -m selftest --jobs 8             # up to 8 suites concurrently (default 4)
  python3 -m selftest --sequential         # one suite at a time, in-process
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

if __package__ in (None, ""):  # allow `python3 scripts/selftest/__main__.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "selftest"

from selftest.core import (  # noqa: E402
    FAIL,
    PASS,
    REPO_ROOT,
    UNAVAILABLE,
    Check,
    Report,
    isolated_env,
    resolve_jsat_binary,
    write_reports,
)

SUITES = [
    "environment", "catalog", "index", "mcp", "reliability", "cli",
    "connect", "sdk", "providers", "improve", "backends", "dashboard",
    "ui", "packaging", "pytest", "live",
]

# Suites that are safe and fast enough to run with no external services,
# no docker and no LLM — the subset a CI job could adopt.
CI_SAFE = ["environment", "catalog", "index", "mcp", "reliability", "cli",
           "connect", "sdk", "improve", "dashboard", "ui"]

# Every suite that depends on the git fixture repo. Keep in sync with the
# `repo and` guards in _run_suite_inline, or a suite silently runs zero checks.
NEEDS_FIXTURE = ("index", "mcp", "reliability", "cli", "sdk",
                 "backends", "improve", "dashboard", "ui")

SUITE_TITLES = {
    "environment": "Environment (real probes, none mocked)",
    "catalog": "Catalog consistency (registries, docs and versions in sync)",
    "index": "Index lifecycle (real parse of 7 languages, real export/import)",
    "mcp": "MCP tools — ALL registered tools over real stdio JSON-RPC",
    "reliability": "MCP reliability engine (budgets, depth cap, auth, RBAC)",
    "cli": "CLI — every top-level command as a real subprocess",
    "connect": "Connectors — real config writes and disconnect round-trips",
    "sdk": "Python SDK — every documented public method, in-process",
    "providers": "AI providers — real completions where credentials exist",
    "improve": "Self-improvement + the privacy invariant",
    "backends": "Graph and cache backends (docker services if reachable)",
    "dashboard": "Dashboard (SSE) and Prometheus metrics",
    "ui": "Studio — `jsat ui` web surface + prompt router over HTTP",
    "packaging": "Packaging — build, metadata, and a clean-venv install of the wheel",
    "pytest": "Test suite (delegates to local_test.sh)",
    "live": "Live agent — REAL headless `claude -p` through the real dispatcher",
}


def _banner(text: str) -> None:
    print(f"\n== {text} ==", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--suite", default="", help=f"comma-separated: {','.join(SUITES)}")
    ap.add_argument("--list-suites", action="store_true")
    ap.add_argument("--ci-safe", action="store_true",
                    help="only suites needing no docker/LLM/external services")
    ap.add_argument("--llm", action="store_true",
                    help="also run checks that need a real AI provider completion")
    ap.add_argument("--live-agent", action="store_true",
                    help="also drive a REAL headless `claude -p` through jsat's real "
                         "--mcp-config and the real /jsat dispatcher. Costs API tokens.")
    ap.add_argument("--full", action="store_true",
                    help="run the pytest suite with no marker filter (needs services)")
    ap.add_argument("--quick", action="store_true", help="skip the pytest suite entirely")
    ap.add_argument("--out", default=None, help="report path prefix")
    ap.add_argument("--jobs", type=int, default=4,
                    help="max suites to run concurrently (default 4; 1 still uses "
                         "workers, just one at a time)")
    ap.add_argument("--sequential", action="store_true",
                    help="run suites in-process, one at a time, printing each check "
                         "live (the pre-parallel behaviour)")
    ap.add_argument("--worker", default="", help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args.worker:
        return _worker_main(args.worker)

    if args.list_suites:
        print("\n".join(SUITES))
        return 0

    if args.suite:
        selected = [s.strip() for s in args.suite.split(",") if s.strip()]
        unknown = [s for s in selected if s not in SUITES]
        if unknown:
            print(f"unknown suite(s): {unknown}; known: {SUITES}", file=sys.stderr)
            return 2
    elif args.ci_safe:
        selected = list(CI_SAFE)
    else:
        selected = [s for s in SUITES if s != "live"]
    if args.live_agent and "live" not in selected:
        selected.append("live")
    if args.quick and "pytest" in selected:
        selected.remove("pytest")

    jsat_bin = resolve_jsat_binary()
    report = Report()
    t_start = time.monotonic()

    from selftest.suites import environment  # noqa: PLC0415

    _banner(SUITE_TITLES["environment"])
    # Fingerprint the user's real ~/.jsat now; the isolation check at the end
    # compares against it. Taken before anything else runs.
    home_jsat_before = environment.snapshot_home_jsat()
    environment.run(report, jsat_bin)

    if not jsat_bin:
        print("\n❌ jsat console script not found — nothing else can be tested.")
        report.add(environment.check_no_state_leak(home_jsat_before))
        _finish(report, args, t_start, jsat_bin, selected)
        return 1

    with tempfile.TemporaryDirectory(prefix="jsat-selftest-") as tmpdir:
        tmp = Path(tmpdir)

        repo: Path | None = None
        if any(s in selected for s in NEEDS_FIXTURE):
            _banner("Fixture repo (real git repo, real multi-language sources)")
            from selftest.fixtures import build_scratch_repo  # noqa: PLC0415
            try:
                repo = build_scratch_repo(tmp)
                report.add(Check("fixture_repo_built", "environment", PASS,
                                 f"fixture repo built and committed at {repo.name}"))
            except Exception as e:
                report.add(Check("fixture_repo_built", "environment", FAIL,
                                 f"could not build the fixture repo: {e}",
                                 remediation="is `git` on PATH?"))

        ordered = [s for s in SUITES if s in selected and s != "environment"]
        if not ordered:
            _banner("No suites selected beyond environment — nothing to run.")
        elif args.sequential:
            _run_sequential(report, ordered, args, jsat_bin, tmp, repo)
        else:
            jobs = _build_jobs(ordered, args, jsat_bin, tmp, repo)
            _run_jobs_parallel(report, jobs, tmp, max(1, args.jobs))

    # Last, so it sees everything every suite did.
    _banner("State isolation (the harness must not touch the real ~/.jsat)")
    report.add(environment.check_no_state_leak(home_jsat_before))

    if not args.sequential:
        _sort_checks_for_display(report)

    return _finish(report, args, t_start, jsat_bin, selected)


def _run_sequential(report: Report, ordered: list[str], args: argparse.Namespace,
                    jsat_bin: str, tmp: Path, repo: Path | None) -> None:
    """Old behaviour: every suite in this process, sharing one env, live output."""
    env = isolated_env(tmp, JSAT_MCP_ALLOW_INSECURE="1")
    for suite in ordered:
        _banner(SUITE_TITLES[suite])
        _run_suite_inline(suite, report, jsat_bin, repo, tmp, env,
                          allow_llm=args.llm, run_all=args.full)


def _run_suite_inline(name: str, report: Report, jsat_bin: str,
                      repo: Path | None, tmp: Path, env: dict[str, str], *,
                      allow_llm: bool, run_all: bool) -> None:
    """Run one suite. The single dispatch table for --sequential, the parent
    pool and the worker subprocesses, so every surface stays in sync.

    `tmp` is the shared tempdir in --sequential mode and this suite's private
    workspace (`ws-<suite>`) under the shared tempdir in parallel mode — every
    JSAT_* env dir is derived from it, so concurrent suites never share state.
    """
    if name == "catalog":
        from selftest.suites import catalog  # noqa: PLC0415
        catalog.run(report, jsat_bin, env)
    elif name == "index":
        if repo is None:
            return
        from selftest.suites import index as index_suite  # noqa: PLC0415
        index_suite.run(report, jsat_bin, repo, tmp, env)
    elif name == "mcp":
        if repo is None:
            return
        from selftest.suites import mcp_tools  # noqa: PLC0415
        mcp_tools.run(report, jsat_bin, repo, tmp, env, allow_llm=allow_llm)
    elif name == "reliability":
        if repo is None:
            return
        from selftest.suites import mcp_tools  # noqa: PLC0415
        mcp_tools.run_reliability(report, jsat_bin, repo, env)
    elif name == "cli":
        if repo is None:
            return
        from selftest.suites import cli as cli_suite  # noqa: PLC0415
        cli_suite.run(report, jsat_bin, repo, tmp, env, allow_llm=allow_llm)
    elif name == "connect":
        from selftest.suites import connect as connect_suite  # noqa: PLC0415
        connect_suite.run(report, jsat_bin, tmp, env)
    elif name == "sdk":
        if repo is None:
            return
        from selftest.suites import sdk as sdk_suite  # noqa: PLC0415
        sdk_suite.run(report, repo, tmp, allow_llm=allow_llm)
    elif name == "providers":
        from selftest.suites import providers  # noqa: PLC0415
        providers.run(report, jsat_bin, tmp, env, allow_llm=allow_llm)
    elif name == "improve":
        if repo is None:
            return
        from selftest.suites import improve as improve_suite  # noqa: PLC0415
        improve_suite.run(report, jsat_bin, repo, tmp, allow_llm=allow_llm)
    elif name == "backends":
        if repo is None:
            return
        from selftest.suites import backends  # noqa: PLC0415
        backends.run(report, jsat_bin, repo, tmp, env)
    elif name == "dashboard":
        if repo is None:
            return
        from selftest.suites import dashboard as dash_suite  # noqa: PLC0415
        dash_suite.run(report, jsat_bin, repo, env)
    elif name == "ui":
        if repo is None:
            return
        from selftest.suites import ui as ui_suite  # noqa: PLC0415
        ui_suite.run(report, jsat_bin, repo, env)
    elif name == "packaging":
        from selftest.suites import packaging  # noqa: PLC0415
        packaging.run(report)
    elif name == "pytest":
        report.add(_check_pytest(run_all=run_all))
    elif name == "live":
        from selftest.suites import live_agent  # noqa: PLC0415
        live_agent.run(report, jsat_bin, REPO_ROOT)
    elif name == "environment":
        # Only ever run directly by the parent, before the pool.
        return
    else:
        report.add(Check(f"unknown_suite_{name}", "harness", FAIL,
                         f"no dispatch for suite {name!r}"))


def _build_jobs(ordered: list[str], args: argparse.Namespace, jsat_bin: str,
                tmp: Path, repo: Path | None) -> list[tuple[str, dict[str, str]]]:
    jobs: list[tuple[str, dict[str, str]]] = []
    for suite in ordered:
        jobs.append((suite, {
            "suite": suite,
            "jsat_bin": jsat_bin or "",
            "repo": str(repo) if (repo is not None and suite in NEEDS_FIXTURE) else "",
            "ws": str(tmp / f"ws-{suite}"),
            "allow_llm": "1" if args.llm else "",
            "run_all": "1" if args.full else "",
        }))
    return jobs


def _run_jobs_parallel(report: Report, jobs: list[tuple[str, dict[str, str]]],
                       tmp: Path, max_jobs: int) -> None:
    """Run each suite in its own subprocess with a private workspace.

    Every JSAT_* dir is redirected into `ws-<suite>`, which is what makes
    concurrent suites safe: they share only the read-only fixture repo and the
    parent's base environment. Per-suite states (os.environ mutations in the
    sdk/index/improve/cli suites, fixed dashboard port) are process-private.
    """
    if not jobs:
        return
    entry = str(Path(__file__).resolve().parent.parent / "jsat_selftest.py")
    workorders = tmp / "workorders"
    reports_dir = tmp / "suite-reports"
    workorders.mkdir(exist_ok=True)
    reports_dir.mkdir(exist_ok=True)

    queue = [suite for suite, _ in jobs]
    payloads = {suite: pay for suite, pay in jobs}
    active: dict[str, tuple[subprocess.Popen[str], float, Path, Path]] = {}

    while queue or active:
        while len(active) < max_jobs and queue:
            suite = queue.pop(0)
            payload = {**payloads[suite]}
            payload["out"] = str(reports_dir / f"{suite}.json")
            wo = workorders / f"{suite}.json"
            err_log = reports_dir / f"{suite}.stderr.log"
            wo.write_text(json.dumps(payload, indent=2))
            with err_log.open("w") as err_fh:
                proc = subprocess.Popen(
                    [sys.executable, entry, "--worker", str(wo)],
                    env=isolated_env(Path(payload["ws"]),
                                     JSAT_MCP_ALLOW_INSECURE="1"),
                    stdout=subprocess.DEVNULL, stderr=err_fh, text=True,
                )
            active[suite] = (proc, time.monotonic(), reports_dir / f"{suite}.json",
                             err_log)

        done = [s for s, (proc, *_rest) in active.items() if proc.poll() is not None]
        if not done:
            time.sleep(0.2)
            continue
        for suite in done:
            proc, t0, out_json, err_log = active.pop(suite)
            elapsed = round(time.monotonic() - t0, 1)
            checks = _load_suite_checks(out_json)
            if proc.returncode != 0:
                err_tail = err_log.read_text()[-1500:] if err_log.exists() else "(none)"
                checks.append(Check(
                    f"{suite}_worker_crash", suite, FAIL,
                    f"worker process exited {proc.returncode} before finishing",
                    detail=err_tail))
            tally = {PASS: 0, FAIL: 0, UNAVAILABLE: 0}
            for c in checks:
                tally[c.status] = tally.get(c.status, 0) + 1
            icon = "❌" if tally[FAIL] else ("⚠️" if tally[UNAVAILABLE] else "✅")
            print(f"\n== {icon} {SUITE_TITLES.get(suite, suite)} — "
                  f"{len(checks)} checks (pass {tally[PASS]}, fail {tally[FAIL]}, "
                  f"unavailable {tally[UNAVAILABLE]}) in {elapsed}s ==", flush=True)
            for c in checks:
                report.add(c)


def _load_suite_checks(out_json: Path) -> list[Check]:
    try:
        data = json.loads(out_json.read_text())
    except Exception:
        return []
    return [Check(**c) for c in data]


def _sort_checks_for_display(report: Report) -> None:
    """Parallel completion order is nondeterministic; the report must not be."""
    order = {s: i for i, s in enumerate(SUITES)}
    report.checks.sort(key=lambda c: (order.get(c.category, 999), c.id))


def _worker_main(wo_path: str) -> int:
    """Entry point for a pooled suite subprocess. Runs one suite into a private
    workspace, writes its checks as JSON for the parent to merge, exits 0.
    No output is printed: the parent prints each suite's results as they land.
    """
    payload = json.loads(Path(wo_path).read_text())
    suite = payload["suite"]
    ws = Path(payload["ws"])
    ws.mkdir(parents=True, exist_ok=True)
    env = isolated_env(ws, JSAT_MCP_ALLOW_INSECURE="1")
    repo = Path(payload["repo"]) if payload.get("repo") else None
    report = Report(quiet=True)
    try:
        _run_suite_inline(suite, report, payload.get("jsat_bin", ""), repo, ws, env,
                          allow_llm=bool(payload.get("allow_llm")),
                          run_all=bool(payload.get("run_all")))
    except Exception as e:  # a crashing suite is a failing suite, never a lost one
        report.add(Check(f"{suite}_crash", suite, FAIL,
                         f"suite raised {type(e).__name__}: {e}",
                         remediation="rerun with `--sequential --suite "
                                     f"{suite}` to trace in-process"))
    out = Path(payload["out"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps([c.__dict__ for c in report.checks], indent=2))
    return 0


def _check_pytest(run_all: bool) -> Check:
    script = REPO_ROOT / "local_test.sh"
    if not script.exists():
        return Check("pytest_suite", "test_suite", UNAVAILABLE,
                     "local_test.sh not found — cannot run the pytest/lint suite")
    cmd = [str(script)] + (["--all"] if run_all else [])
    t0 = time.monotonic()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           cwd=str(REPO_ROOT), timeout=1800)
    except subprocess.TimeoutExpired:
        return Check("pytest_suite", "test_suite", FAIL,
                     "local_test.sh timed out after 1800s")
    tail = "\n".join((r.stdout + r.stderr).splitlines()[-50:])
    status = PASS if r.returncode == 0 else FAIL
    return Check("pytest_suite", "test_suite", status,
                 f"local_test.sh {'--all ' if run_all else ''}exited {r.returncode}",
                 detail=tail, elapsed_ms=round((time.monotonic() - t0) * 1000))


def _finish(report: Report, args: argparse.Namespace, t_start: float,
            jsat_bin: str | None, selected: list[str]) -> int:
    tally = report.tally()
    meta = {
        "suites": ",".join(selected),
        "jsat_binary": jsat_bin or "(not found)",
        "parallel": not args.sequential,
        "jobs": args.jobs,
        "python": sys.version.split()[0],
        "llm_enabled": args.llm,
        "live_agent": args.live_agent,
        "docker": "yes" if _docker_ok() else "no",
        "duration_s": round(time.monotonic() - t_start, 1),
    }
    prefix = Path(args.out) if args.out else \
        REPO_ROOT / f"jsat-selftest-report-{int(time.time())}"
    json_path, md_path = write_reports(report, prefix, meta)

    print(f"\n{'=' * 68}")
    print(f"✅ {tally[PASS]} passed   ❌ {tally[FAIL]} failed   "
          f"⚠️  {tally[UNAVAILABLE]} unavailable   "
          f"({tally['total']} checks, {meta['duration_s']}s)")
    print(f"Report: {json_path}")
    print(f"        {md_path}")
    print(f"{'=' * 68}")
    return 1 if tally[FAIL] else 0


def _docker_ok() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "ps"], capture_output=True,
                              timeout=10).returncode == 0
    except Exception:
        return False


if __name__ == "__main__":
    sys.exit(main())