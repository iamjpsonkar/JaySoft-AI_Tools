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

Usage:
  python3 -m selftest                      # everything available, no LLM cost
  python3 -m selftest --llm                # also drive real AI provider calls
  python3 -m selftest --live-agent         # also drive real `claude -p` skills
  python3 -m selftest --suite mcp,cli      # just these suites
  python3 -m selftest --list-suites
  python3 -m selftest --out /tmp/report
"""
from __future__ import annotations

import argparse
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
    "packaging", "pytest", "live",
]

# Suites that are safe and fast enough to run with no external services,
# no docker and no LLM — the subset a CI job could adopt.
CI_SAFE = ["environment", "catalog", "index", "mcp", "reliability", "cli",
           "connect", "sdk", "improve", "dashboard"]


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
    args = ap.parse_args()

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

    _banner("Environment (real probes, none mocked)")
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
        env = isolated_env(tmp, JSAT_MCP_ALLOW_INSECURE="1")

        repo: Path | None = None
        # Every suite that needs real code to analyse. Keep in sync with the
        # `and repo` guards below, or a suite silently runs zero checks.
        NEEDS_FIXTURE = ("index", "mcp", "reliability", "cli", "sdk",
                         "backends", "improve", "dashboard")
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

        if "catalog" in selected:
            _banner("Catalog consistency (registries, docs and versions in sync)")
            from selftest.suites import catalog  # noqa: PLC0415
            catalog.run(report, jsat_bin, env)

        if "index" in selected and repo:
            _banner("Index lifecycle (real parse of 7 languages, real export/import)")
            from selftest.suites import index as index_suite  # noqa: PLC0415
            index_suite.run(report, jsat_bin, repo, tmp, env)

        if "mcp" in selected and repo:
            _banner("MCP tools — ALL registered tools over real stdio JSON-RPC")
            from selftest.suites import mcp_tools  # noqa: PLC0415
            mcp_tools.run(report, jsat_bin, repo, tmp, env, allow_llm=args.llm)

        if "reliability" in selected and repo:
            _banner("MCP reliability engine (budgets, depth cap, auth, RBAC)")
            from selftest.suites import mcp_tools  # noqa: PLC0415
            mcp_tools.run_reliability(report, jsat_bin, repo, env)

        if "cli" in selected and repo:
            _banner("CLI — every top-level command as a real subprocess")
            from selftest.suites import cli as cli_suite  # noqa: PLC0415
            cli_suite.run(report, jsat_bin, repo, tmp, env, allow_llm=args.llm)

        if "connect" in selected:
            _banner("Connectors — real config writes and disconnect round-trips")
            from selftest.suites import connect as connect_suite  # noqa: PLC0415
            connect_suite.run(report, jsat_bin, tmp, env)

        if "sdk" in selected and repo:
            _banner("Python SDK — every documented public method, in-process")
            from selftest.suites import sdk as sdk_suite  # noqa: PLC0415
            sdk_suite.run(report, repo, tmp, allow_llm=args.llm)

        if "providers" in selected:
            _banner("AI providers — real completions where credentials exist")
            from selftest.suites import providers  # noqa: PLC0415
            providers.run(report, jsat_bin, tmp, env, allow_llm=args.llm)

        if "improve" in selected and repo:
            _banner("Self-improvement + the privacy invariant")
            from selftest.suites import improve as improve_suite  # noqa: PLC0415
            improve_suite.run(report, jsat_bin, repo, tmp, allow_llm=args.llm)

        if "backends" in selected and repo:
            _banner("Graph and cache backends (docker services if reachable)")
            from selftest.suites import backends  # noqa: PLC0415
            backends.run(report, jsat_bin, repo, tmp, env)

        if "dashboard" in selected and repo:
            _banner("Dashboard (SSE) and Prometheus metrics")
            from selftest.suites import dashboard as dash_suite  # noqa: PLC0415
            dash_suite.run(report, jsat_bin, repo, env)

    if "packaging" in selected:
        _banner("Packaging — build, metadata, and a clean-venv install of the wheel")
        from selftest.suites import packaging  # noqa: PLC0415
        packaging.run(report)

    if "live" in selected:
        _banner("Live agent — REAL headless `claude -p` through the real dispatcher")
        from selftest.suites import live_agent  # noqa: PLC0415
        live_agent.run(report, jsat_bin, REPO_ROOT)

    if "pytest" in selected:
        _banner("Test suite (delegates to local_test.sh)")
        report.add(_check_pytest(run_all=args.full))

    # Last, so it sees everything every suite did.
    _banner("State isolation (the harness must not touch the real ~/.jsat)")
    report.add(environment.check_no_state_leak(home_jsat_before))

    return _finish(report, args, t_start, jsat_bin, selected)


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
