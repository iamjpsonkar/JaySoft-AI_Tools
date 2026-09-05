"""
Phase D — every top-level CLI command, as a real subprocess.

Three groups, handled differently because they carry different risk:

* **Read-only / idempotent** — run directly against the fixture repo.
* **Destructive** (`clean`, `remove`, `disconnect`) — run only with
  JSAT_DATA_DIR and HOME redirected into the temp dir, so a path-resolution
  bug cannot reach the user's real repo or home.
* **Launchers and lifecycle** — these exist to exec another program, so a
  recorder stub is placed on PATH in place of that program and the assertion
  is made against the real argv and the real generated `--mcp-config`.
  Every line of JSAT under test is real; only the third-party binary is
  substituted, because "did we invoke claude correctly" cannot be observed
  any other way without a TTY.

There is also a coverage gate: every command Typer advertises in `--help`
must appear in this file's matrix, so a new command cannot ship untested.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

from ..core import (
    FAIL,
    PASS,
    UNAVAILABLE,
    Check,
    Report,
    make_config_capturing_recorder,
    read_recordings,
    run_cli,
    timed,
)
from ..fixtures import scratch_facts

# Commands that are inherently interactive (they open a REPL or attach to a
# TTY) and so are verified via --help plus their side effects rather than by
# running them bare.
INTERACTIVE = {"shell", "bob", "gpt", "ollama", "cursor", "windsurf", "zed",
               "gemini", "claude", "codex", "opencode"}

# Commands verified by a dedicated check elsewhere in the harness.
COVERED_ELSEWHERE = {
    "mcp-server": "mcp suite drives it over real stdio JSON-RPC",
    "connect": "connect suite round-trips every target",
    "disconnect": "connect suite round-trips every target",
    "ai": "providers suite exercises status/use/test/models",
    "improve": "improve suite drives it end to end",
    "ci-setup": "catalog suite asserts the generated workflow is valid",
    "index": "index suite covers full/incremental/export/import",
    "export": "index suite covers the export/import round trip",
    "import": "index suite covers the export/import round trip",
    "update": "would mutate the installed package from PyPI; asserted via --help only",
}


def _all_cli_commands(jsat_bin: str, env: dict[str, str]) -> list[str]:
    r = subprocess.run([jsat_bin, "--help"], capture_output=True, text=True,
                       timeout=60, env=env)
    names = []
    for line in r.stdout.splitlines():
        m = re.match(r"^\s*│\s+([a-z][a-z0-9-]*)\s{2,}", line)
        if m:
            names.append(m.group(1))
    return sorted(set(names))


@timed
def check_version(jsat_bin: str, env: dict[str, str]) -> Check:
    r = run_cli(jsat_bin, ["version"], env)
    if r.returncode == 0 and r.stdout.strip():
        return Check("cli_version", "cli", PASS, "jsat version ran",
                     detail=r.stdout.strip()[:200])
    return Check("cli_version", "cli", FAIL, "jsat version failed",
                 detail=f"rc={r.returncode} stderr={r.stderr[:300]}")


@timed
def check_help(jsat_bin: str, env: dict[str, str]) -> Check:
    r = run_cli(jsat_bin, ["--help"], env)
    if r.returncode == 0 and "Usage" in r.stdout:
        return Check("cli_help", "cli", PASS, "jsat --help ran")
    return Check("cli_help", "cli", FAIL, "jsat --help failed",
                 detail=f"rc={r.returncode} stderr={r.stderr[:300]}")


@timed
def check_every_command_has_help(jsat_bin: str, env: dict[str, str]) -> Check:
    """`--help` on every command must exit 0. This catches a command whose
    Typer signature is malformed or whose lazy import is broken at parse
    time — cheap, and it touches all 38."""
    cmds = _all_cli_commands(jsat_bin, env)
    if not cmds:
        return Check("cli_all_help", "cli", FAIL,
                     "could not enumerate commands from `jsat --help`")
    broken = {}
    for c in cmds:
        r = run_cli(jsat_bin, [c, "--help"], env, timeout=45)
        if r.returncode != 0:
            broken[c] = f"rc={r.returncode} {r.stderr[:120]}"
    if broken:
        return Check("cli_all_help", "cli", FAIL,
                     f"{len(broken)} of {len(cmds)} commands fail `--help`",
                     detail=json.dumps(broken, indent=2)[:800])
    return Check("cli_all_help", "cli", PASS,
                 f"all {len(cmds)} top-level commands respond to --help")


@timed
def check_command_coverage(jsat_bin: str, env: dict[str, str],
                           exercised: set[str]) -> Check:
    """Coverage gate: a command Typer advertises but nothing here runs."""
    cmds = set(_all_cli_commands(jsat_bin, env))
    # The parser depends on Rich's box-drawing output; if it ever yields
    # nothing, "all 0 commands are exercised" would be a green light for zero
    # coverage. Treat an empty parse as a failure of the gate itself.
    if len(cmds) < 20:
        return Check("cli_coverage_complete", "cli", FAIL,
                     f"only parsed {len(cmds)} command(s) from `jsat --help`, "
                     "so the coverage gate cannot be trusted",
                     detail=f"parsed={sorted(cmds)}",
                     remediation="fix _all_cli_commands' parsing of the "
                                 "Typer/Rich help output")
    accounted = exercised | INTERACTIVE | set(COVERED_ELSEWHERE)
    missing = sorted(cmds - accounted)
    if missing:
        return Check("cli_coverage_complete", "cli", FAIL,
                     f"{len(missing)} CLI command(s) have no self-test coverage",
                     detail=", ".join(missing),
                     remediation="add a check in scripts/selftest/suites/cli.py")
    return Check("cli_coverage_complete", "cli", PASS,
                 f"all {len(cmds)} CLI commands are exercised or explicitly "
                 f"accounted for")


@timed
def check_doctor(jsat_bin: str, env: dict[str, str], cwd: str) -> Check:
    r = run_cli(jsat_bin, ["doctor", "--json"], env, cwd=cwd, timeout=90)
    if r.returncode != 0:
        return Check("cli_doctor", "cli", FAIL, "jsat doctor exited non-zero",
                     detail=f"rc={r.returncode} stderr={r.stderr[:400]}")
    try:
        payload = json.loads(r.stdout)
    except json.JSONDecodeError as e:
        return Check("cli_doctor", "cli", FAIL,
                     f"doctor --json produced invalid JSON: {e}",
                     detail=r.stdout[:400],
                     remediation="something is writing to stdout alongside the JSON")
    return Check("cli_doctor", "cli", PASS,
                 "jsat doctor --json returned parseable JSON",
                 detail=json.dumps(payload)[:300])


@timed
def check_status(jsat_bin: str, env: dict[str, str], repo: Path) -> Check:
    r = run_cli(jsat_bin, ["doctor"], env, cwd=str(repo), timeout=90)
    if r.returncode == 0:
        return Check("cli_status", "cli", PASS, "jsat doctor (human output) ran")
    return Check("cli_status", "cli", FAIL, "jsat doctor failed",
                 detail=f"rc={r.returncode} {r.stderr[:300]}")


@timed
def check_init(jsat_bin: str, env: dict[str, str], tmp: Path) -> Check:
    work = tmp / "init-target"
    work.mkdir(exist_ok=True)
    r = run_cli(jsat_bin, ["init"], {**env, "HOME": str(work)},
                cwd=str(work), timeout=60)
    written = list(work.rglob("config.yaml")) + list(work.rglob(".jsat.yaml"))
    if r.returncode == 0 and written:
        import yaml
        try:
            cfg = yaml.safe_load(written[0].read_text())
        except Exception as e:
            return Check("cli_init", "cli", FAIL,
                         f"jsat init wrote unparseable YAML: {e}")
        return Check("cli_init", "cli", PASS,
                     f"jsat init wrote a valid config ({written[0].name})",
                     detail=json.dumps(cfg)[:300])
    return Check("cli_init", "cli", FAIL,
                 "jsat init did not produce a config file",
                 detail=f"rc={r.returncode} out={r.stdout[:200]} err={r.stderr[:200]}")


@timed
def check_tokens(jsat_bin: str, env: dict[str, str]) -> Check:
    r = run_cli(jsat_bin, ["tokens", "hello world this is a token counting test"],
                env, timeout=60)
    if r.returncode == 0 and re.search(r"\d", r.stdout):
        return Check("cli_tokens", "cli", PASS,
                     "jsat tokens returned a count", detail=r.stdout.strip()[:200])
    return Check("cli_tokens", "cli", FAIL, "jsat tokens failed",
                 detail=f"rc={r.returncode} out={r.stdout[:200]} err={r.stderr[:200]}")


@timed
def check_note_and_session(jsat_bin: str, env: dict[str, str],
                           repo: Path) -> Check:
    """note add → note list → note search, then session list, all for real."""
    add = run_cli(jsat_bin, ["note", "add", "payments uses integer minor units"],
                  env, cwd=str(repo), timeout=90)
    if add.returncode != 0:
        return Check("cli_note_session", "cli", FAIL,
                     "jsat note add failed",
                     detail=f"rc={add.returncode} {add.stderr[:300]}")
    lst = run_cli(jsat_bin, ["note", "list"], env, cwd=str(repo), timeout=90)
    found = "minor units" in lst.stdout
    search = run_cli(jsat_bin, ["note", "search", "minor"], env,
                     cwd=str(repo), timeout=90)
    sess = run_cli(jsat_bin, ["session", "list"], env, cwd=str(repo), timeout=60)
    problems = []
    if not found:
        problems.append("note list did not return the note just added")
    if search.returncode != 0:
        problems.append(f"note search rc={search.returncode}")
    if sess.returncode != 0:
        problems.append(f"session list rc={sess.returncode}")
    if problems:
        return Check("cli_note_session", "cli", FAIL,
                     "; ".join(problems),
                     detail=f"list={lst.stdout[:250]} search={search.stdout[:200]}")
    return Check("cli_note_session", "cli", PASS,
                 "note add/list/search and session list all round-tripped")


@timed
def check_knowledge_ingest(jsat_bin: str, env: dict[str, str],
                           repo: Path) -> Check:
    """The fixture repo ships a CLAUDE.md and an ADR for this to find."""
    r = run_cli(jsat_bin, ["knowledge-ingest", "--repo", str(repo)],
                env, cwd=str(repo), timeout=180)
    if r.returncode == 0:
        return Check("cli_knowledge_ingest", "cli", PASS,
                     "jsat knowledge-ingest scanned the fixture docs",
                     detail=r.stdout.strip()[:300])
    return Check("cli_knowledge_ingest", "cli", FAIL,
                 "jsat knowledge-ingest failed",
                 detail=f"rc={r.returncode} {r.stderr[:400]}")


@timed
def check_skills(jsat_bin: str, env: dict[str, str], repo: Path) -> Check:
    r = run_cli(jsat_bin, ["skills", "list"], env, cwd=str(repo), timeout=60)
    if r.returncode != 0:
        return Check("cli_skills", "cli", FAIL, "jsat skills list failed",
                     detail=f"rc={r.returncode} {r.stderr[:300]}")
    return Check("cli_skills", "cli", PASS, "jsat skills list ran",
                 detail=r.stdout.strip()[:250])


@timed
def check_clean_is_scoped(jsat_bin: str, env: dict[str, str],
                          tmp: Path, repo: Path) -> Check:
    """`clean --all` must remove only the redirected data dir's artifacts and
    leave the source tree untouched.

    Runs against its OWN data dir: pointing it at the shared one deleted the
    graph that connect/sdk/providers/improve/backends/dashboard still needed,
    making their results depend on suite ordering.
    """
    data_dir = tmp / "clean-scoped-data"
    env = {**env, "JSAT_DATA_DIR": str(data_dir)}
    run_cli(jsat_bin, ["index", str(repo)], env, timeout=180)
    before_src = sorted(p.name for p in repo.iterdir())
    r = run_cli(jsat_bin, ["clean", "--all"], env, cwd=str(repo), timeout=60)
    after_src = sorted(p.name for p in repo.iterdir())
    if r.returncode != 0:
        return Check("cli_clean_scoped", "cli", FAIL,
                     "jsat clean --all exited non-zero",
                     detail=f"rc={r.returncode} {r.stderr[:300]}")
    if before_src != after_src:
        return Check("cli_clean_scoped", "cli", FAIL,
                     "jsat clean --all modified the source tree",
                     detail=f"before={before_src} after={after_src}")
    if (data_dir / "graph" / "graph.db").exists():
        return Check("cli_clean_scoped", "cli", FAIL,
                     "jsat clean --all left the graph database in place",
                     detail=f"still present: {data_dir / 'graph' / 'graph.db'}",
                     remediation="check the --graph/--all branches of cmd_clean")
    return Check("cli_clean_scoped", "cli", PASS,
                 "jsat clean --all removed the graph from the data dir and "
                 "left the source tree untouched")


@timed
def check_remove_is_scoped(jsat_bin: str, env: dict[str, str],
                           tmp: Path) -> Check:
    """`remove --yes` on a throwaway repo must not touch anything outside it."""
    victim = tmp / "remove-target"
    victim.mkdir(exist_ok=True)
    (victim / "keep_me.py").write_text("x = 1\n")
    home = tmp / "remove-home"
    home.mkdir(exist_ok=True)
    (home / "sentinel.txt").write_text("must survive\n")
    scoped = {**env, "HOME": str(home),
              "JSAT_DATA_DIR": str(tmp / "remove-data")}
    run_cli(jsat_bin, ["index", str(victim)], scoped, timeout=90)
    r = run_cli(jsat_bin, ["remove", "--yes"], scoped, cwd=str(victim), timeout=60)
    if not (victim / "keep_me.py").exists():
        return Check("cli_remove_scoped", "cli", FAIL,
                     "jsat remove deleted a source file it did not create",
                     detail=f"rc={r.returncode}")
    if not (home / "sentinel.txt").exists():
        return Check("cli_remove_scoped", "cli", FAIL,
                     "jsat remove deleted an unrelated file in HOME",
                     detail=f"rc={r.returncode}")
    if r.returncode != 0:
        return Check("cli_remove_scoped", "cli", FAIL,
                     "jsat remove --yes exited non-zero",
                     detail=f"rc={r.returncode} {r.stderr[:300]}")
    return Check("cli_remove_scoped", "cli", PASS,
                 "jsat remove --yes cleaned JSAT artifacts and left source "
                 "files and unrelated HOME content intact")


# ── Launchers: real jsat, recorder stub for the third-party binary ─────────

LAUNCHER_MATRIX = {
    # command -> the binary it is expected to exec
    "claude": "claude",
    "codex": "codex",
    "opencode": "opencode",
    "cursor": "cursor",
    "windsurf": "windsurf",
    "zed": "zed",
    "gemini": "gemini",
}


@timed
def check_launcher(jsat_bin: str, env: dict[str, str], tmp: Path, repo: Path,
                   command: str, target_bin: str) -> Check:
    """Run the real launcher with a recorder standing in for the target tool."""
    stub_dir = tmp / f"stub-{command}"
    stub_dir.mkdir(parents=True, exist_ok=True)
    log = stub_dir / "argv.jsonl"
    # The recorder must also snapshot any file passed via --mcp-config: jsat
    # writes it to a NamedTemporaryFile and deletes it once the child exits,
    # so reading it afterwards always fails. Capturing it inside the stub is
    # the only point at which it exists.
    make_config_capturing_recorder(stub_dir / target_bin, log)
    home = tmp / f"launch-home-{command}"
    home.mkdir(parents=True, exist_ok=True)
    scoped = {**env,
              "PATH": f"{stub_dir}{os.pathsep}{env.get('PATH', '')}",
              "HOME": str(home)}
    r = run_cli(jsat_bin, [command, "--repo", str(repo)], scoped,
                cwd=str(repo), timeout=120)
    recs = read_recordings(log)
    if not recs:
        return Check(f"cli_launch_{command}", "cli_launchers", FAIL,
                     f"jsat {command} never invoked `{target_bin}`",
                     detail=f"rc={r.returncode} out={r.stdout[-400:]} "
                            f"err={r.stderr[-400:]}",
                     remediation="the launcher exited before exec; read the "
                                 "stdout above for the reason it gave")
    argv = recs[0]["argv"]
    captured = recs[0].get("configs", {})
    # If the launcher passes an --mcp-config, it must be valid JSON naming the
    # jsat server: a malformed one silently disables every tool in the
    # launched session, which looks like "jsat does nothing" to the user.
    cfg_problem = ""
    saw_config = False
    for i, a in enumerate(argv):
        if a in ("--mcp-config", "--mcp-config-file") and i + 1 < len(argv):
            saw_config = True
            raw = argv[i + 1]
            blob_text = captured.get(raw, raw)
            try:
                blob = json.loads(blob_text)
            except Exception as e:
                cfg_problem = f"--mcp-config was not valid JSON: {e}"
                break
            if "jsat" not in json.dumps(blob):
                cfg_problem = "--mcp-config did not name the jsat MCP server"
                break
            servers = blob.get("mcpServers", {})
            entry = servers.get("jsat", {})
            if "mcp-server" not in " ".join(entry.get("args", [])):
                cfg_problem = ("the jsat MCP entry does not invoke "
                               "`jsat mcp-server`")
    if cfg_problem:
        return Check(f"cli_launch_{command}", "cli_launchers", FAIL, cfg_problem,
                     detail=f"argv={' '.join(argv)[:300]} "
                            f"configs={json.dumps(captured)[:400]}")
    note = "with a valid --mcp-config" if saw_config else "(no --mcp-config used)"
    return Check(f"cli_launch_{command}", "cli_launchers", PASS,
                 f"jsat {command} exec'd `{target_bin}` {note}",
                 detail=" ".join(argv)[:400])


# ── Lifecycle: real process tracking, real kill ────────────────────────────

@timed
def check_lifecycle_start_ps_stop(jsat_bin: str, env: dict[str, str],
                                  tmp: Path, repo: Path) -> Check:
    """start → ps → stop against a real long-lived child process.

    `jsat start` runs the tool in the FOREGROUND and returns its exit code,
    so it is launched as a background process here and `ps`/`stop` are driven
    against it from this one. The stub sleeps instead of exiting so there is a
    real process tree for `stop` to kill — the only way to exercise the
    descendant walk and the start-time PID token.
    """
    stub_dir = tmp / "stub-lifecycle"
    stub_dir.mkdir(parents=True, exist_ok=True)
    log = stub_dir / "argv.jsonl"
    stub = stub_dir / "claude"
    stub.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys, pathlib, time\n"
        f"pathlib.Path({str(log)!r}).open('a').write("
        "json.dumps({'argv': sys.argv, 'pid': os.getpid()}) + '\\n')\n"
        "time.sleep(600)\n"
    )
    stub.chmod(0o755)
    home = tmp / "lifecycle-home"
    home.mkdir(parents=True, exist_ok=True)
    runtime = tmp / "lifecycle-runtime"
    scoped = {**env,
              "PATH": f"{stub_dir}{os.pathsep}{env.get('PATH', '')}",
              "HOME": str(home),
              "JSAT_RUNTIME_DIR": str(runtime)}

    proc = subprocess.Popen(
        [jsat_bin, "start", "claude", "--repo", str(repo)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=scoped,
        cwd=str(repo))
    try:
        # Wait for the stub to actually be exec'd.
        child_pid = None
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            recs = read_recordings(log)
            if recs:
                child_pid = recs[0].get("pid")
                break
            if proc.poll() is not None:
                out, err = proc.communicate(timeout=10)
                return Check("cli_lifecycle", "cli_lifecycle", FAIL,
                             f"jsat start exited (rc={proc.returncode}) without "
                             "launching the tracked process",
                             detail=f"out={out[-400:]} err={err[-400:]}")
            time.sleep(0.5)
        if child_pid is None:
            return Check("cli_lifecycle", "cli_lifecycle", FAIL,
                         "jsat start never invoked the tracked process")

        # Give save_record a moment to land.
        deadline = time.monotonic() + 30
        runtime_files: list[Path] = []
        while time.monotonic() < deadline:
            runtime_files = list(runtime.glob("*.json")) if runtime.exists() else []
            if runtime_files:
                break
            time.sleep(0.5)

        ps = run_cli(jsat_bin, ["ps"], scoped, cwd=str(repo), timeout=60)
        stop = run_cli(jsat_bin, ["stop", "claude"], scoped, cwd=str(repo),
                       timeout=90)

        alive = True
        for _ in range(40):
            if not Path(f"/proc/{child_pid}").exists():
                alive = False
                break
            time.sleep(0.25)

        problems = []
        if not runtime_files:
            problems.append("no runtime record was written, so `ps`/`stop` "
                            "have nothing to track")
        if ps.returncode != 0:
            problems.append(f"jsat ps rc={ps.returncode} {ps.stderr[:120]}")
        elif "claude" not in ps.stdout.lower():
            problems.append("jsat ps did not list the running client")
        if stop.returncode != 0:
            problems.append(f"jsat stop rc={stop.returncode} {stop.stderr[:120]}")
        if alive:
            problems.append(f"child pid {child_pid} survived `jsat stop`")
        if problems:
            return Check("cli_lifecycle", "cli_lifecycle", FAIL,
                         "; ".join(problems),
                         detail=f"ps={ps.stdout[:300]} stop={stop.stdout[:300]}")
        return Check("cli_lifecycle", "cli_lifecycle", PASS,
                     f"start tracked a real pid, ps listed it, and stop killed "
                     f"the process tree (pid {child_pid} gone)",
                     detail=f"runtime_record={runtime_files[0].name}")
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


@timed
def check_pid_reuse_guard(tmp: Path) -> Check:
    """A recycled PID must not be mistaken for the tracked process.

    `_lifecycle.process_token` fingerprints a process by its start time, so a
    record whose token disagrees with the live process must read as "not
    running". Verified against this interpreter's own real pid, which is
    guaranteed to exist.
    """
    try:
        from jsat._lifecycle import LifecycleRecord, is_running, process_token
    except Exception as e:
        return Check("lifecycle_pid_reuse_guard", "cli_lifecycle", UNAVAILABLE,
                     f"could not import the lifecycle helpers: {e}")
    my_pid = os.getpid()
    real_token = process_token(my_pid)
    if not real_token:
        return Check("lifecycle_pid_reuse_guard", "cli_lifecycle", UNAVAILABLE,
                     "process_token returned nothing on this platform")

    def rec(token: str) -> LifecycleRecord:
        return LifecycleRecord(
            tool="selftest", via="native", repo=str(tmp), model=None,
            pid=my_pid, process_token=token, status="running",
            started_at=0.0, updated_at=0.0, exit_code=None,
        )

    if not is_running(rec(real_token)):
        return Check("lifecycle_pid_reuse_guard", "cli_lifecycle", FAIL,
                     "a record with the CORRECT start-time token reported "
                     "not-running for a live pid",
                     remediation="check process_token/is_running in "
                                 "jsat/_lifecycle.py")
    if is_running(rec(real_token + "-stale")):
        return Check("lifecycle_pid_reuse_guard", "cli_lifecycle", FAIL,
                     "a record with a MISMATCHED start-time token reported "
                     "running — a recycled PID would be misdetected as the "
                     "tracked client",
                     remediation="check process_token/is_running in "
                                 "jsat/_lifecycle.py")
    return Check("lifecycle_pid_reuse_guard", "cli_lifecycle", PASS,
                 "the start-time token correctly distinguishes a live pid from "
                 "a recycled one")


@timed
def check_analysis_commands(jsat_bin: str, env: dict[str, str], tmp: Path,
                            repo: Path) -> Check:
    """blast-radius / contract-check / security-review — the three commands
    `ci-setup` generates, exercised the way the generated workflow calls them.

    Includes the git-range form of --diff, which is what the template emits
    and which used to be forwarded as diff *text*: the tool found no files,
    reported zero impact and exited 0, so the CI step was green whatever the
    change contained.
    """
    facts = scratch_facts()
    problems: list[str] = []

    # Self-contained: blast radius resolves changed files against the graph,
    # so this needs its own index rather than depending on the `index` suite
    # having run first (`--suite cli` alone would otherwise report zero
    # impact and look like the git-range bug).
    idx = run_cli(jsat_bin, ["index", str(repo), "--force"], env, timeout=240)
    if idx.returncode != 0:
        return Check("cli_analysis_commands", "cli", FAIL,
                     "could not index the fixture repo for the analysis checks",
                     detail=f"rc={idx.returncode} {idx.stderr[-300:]}")

    # A git range, as the generated workflow passes it.
    out_md = tmp / "blast.md"
    br = run_cli(jsat_bin, ["blast-radius", "--diff",
                            f"{facts['old_ref']}...{facts['new_ref']}",
                            "--output", str(out_md), "--repo", str(repo)],
                 env, cwd=str(repo), timeout=180)
    if br.returncode != 0:
        problems.append(f"blast-radius --diff <range> rc={br.returncode} "
                        f"{br.stderr[:120]}")
    elif "impacted: 0" in br.stdout:
        problems.append("blast-radius --diff <range> found nothing on a diff "
                        "that changes indexed code — the range is probably "
                        "being treated as literal diff text")
    elif not out_md.exists():
        problems.append("blast-radius --output wrote no report")

    # A bad range must fail loudly rather than report an empty result.
    bad = run_cli(jsat_bin, ["blast-radius", "--diff", "no-such-ref...HEAD",
                             "--repo", str(repo)], env, cwd=str(repo),
                  timeout=120)
    if bad.returncode == 0:
        problems.append("an unresolvable --diff range exited 0")

    # A symbol target.
    sym = run_cli(jsat_bin, ["blast-radius", facts["tested_function"],
                             "--repo", str(repo)], env, cwd=str(repo),
                  timeout=180)
    if sym.returncode != 0:
        problems.append(f"blast-radius <symbol> rc={sym.returncode}")

    # contract-check across the fixture's two real refs; v1→v2 is breaking,
    # so the default --fail-on-breaking must make it exit non-zero.
    cc = run_cli(jsat_bin, ["contract-check", "--base", str(facts["old_ref"]),
                            "--head", str(facts["new_ref"]), "--repo", str(repo)],
                 env, cwd=str(repo), timeout=180)
    if cc.returncode == 0:
        problems.append("contract-check exited 0 on a breaking API change "
                        "despite --fail-on-breaking being the default")
    if "breaking" not in (cc.stdout + cc.stderr).lower():
        problems.append("contract-check output does not mention breaking changes")

    # security-review, including the SARIF the CI step uploads.
    sarif = tmp / "security.sarif"
    sr = run_cli(jsat_bin, ["security-review", str(repo), "--severity", "low",
                            "--sarif", str(sarif), "--no-deps",
                            "--repo", str(repo)],
                 env, cwd=str(repo), timeout=300)
    if sr.returncode != 0:
        problems.append(f"security-review rc={sr.returncode} {sr.stderr[:120]}")
    elif not sarif.exists():
        problems.append("--sarif wrote no file")
    else:
        try:
            doc = json.loads(sarif.read_text())
            if doc.get("version") != "2.1.0":
                problems.append(f"SARIF version is {doc.get('version')!r}")
            results = doc["runs"][0]["results"]
            if not results:
                problems.append("SARIF has no results despite the planted secret")
            elif not results[0]["locations"][0]["physicalLocation"][
                    "artifactLocation"]["uri"]:
                problems.append("SARIF result has no artifact URI")
        except Exception as e:
            problems.append(f"SARIF is not valid: {type(e).__name__}: {e}")

    if problems:
        return Check("cli_analysis_commands", "cli", FAIL,
                     f"{len(problems)} problem(s) in the CI analysis commands",
                     detail="; ".join(problems))
    return Check("cli_analysis_commands", "cli", PASS,
                 "blast-radius (range, bad range, symbol), contract-check "
                 "(exits non-zero on breaking) and security-review (valid "
                 "SARIF 2.1.0) all behave as the generated CI expects")


def run(report: Report, jsat_bin: str, repo: Path, tmp: Path,
        env: dict[str, str], *, allow_llm: bool) -> None:
    exercised: set[str] = set()

    report.add(check_version(jsat_bin, env)); exercised.add("version")
    report.add(check_help(jsat_bin, env))
    report.add(check_every_command_has_help(jsat_bin, env))
    report.add(check_doctor(jsat_bin, env, str(tmp))); exercised.add("doctor")
    report.add(check_status(jsat_bin, env, repo))
    report.add(check_init(jsat_bin, env, tmp)); exercised.add("init")
    report.add(check_tokens(jsat_bin, env)); exercised.add("tokens")
    report.add(check_note_and_session(jsat_bin, env, repo))
    exercised |= {"note", "session"}
    report.add(check_knowledge_ingest(jsat_bin, env, repo))
    exercised.add("knowledge-ingest")
    report.add(check_skills(jsat_bin, env, repo)); exercised.add("skills")
    report.add(check_analysis_commands(jsat_bin, env, tmp, repo))
    exercised |= {"blast-radius", "contract-check", "security-review"}

    for command, target in LAUNCHER_MATRIX.items():
        report.add(check_launcher(jsat_bin, env, tmp, repo, command, target))
        exercised.add(command)

    report.add(check_lifecycle_start_ps_stop(jsat_bin, env, tmp, repo))
    exercised |= {"start", "stop", "ps"}
    report.add(check_pid_reuse_guard(tmp))
    for c in ("restart", "resume"):
        r = run_cli(jsat_bin, [c, "--help"], env, timeout=45)
        report.add(Check(f"cli_{c}_help", "cli_lifecycle",
                         PASS if r.returncode == 0 else FAIL,
                         f"jsat {c} --help "
                         f"{'ran' if r.returncode == 0 else 'failed'}",
                         detail=r.stderr[:200]))
        exercised.add(c)

    # LLM-backed CLI tools: real provider calls, so gated.
    for cmd, args in (("short", ["short", "what does validate_amount do?"]),
                      ("crack", ["crack", "should currency be a column?",
                                 "--rounds", "1"]),
                      ("prompt", ["prompt", "how do i add a currency field"])):
        if not allow_llm:
            report.add(Check(f"cli_{cmd}", "cli", UNAVAILABLE,
                             "needs a real AI provider completion; skipped "
                             "without --llm"))
            exercised.add(cmd)
            continue
        r = run_cli(jsat_bin, args, env, cwd=str(repo), timeout=600)
        report.add(Check(f"cli_{cmd}", "cli",
                         PASS if r.returncode == 0 else FAIL,
                         f"jsat {cmd} "
                         f"{'produced output' if r.returncode == 0 else 'failed'}",
                         detail=(r.stdout or r.stderr)[:400]))
        exercised.add(cmd)

    # Destructive ones last: they delete the data dir the checks above used.
    report.add(check_remove_is_scoped(jsat_bin, env, tmp)); exercised.add("remove")
    report.add(check_clean_is_scoped(jsat_bin, env, tmp, repo))
    exercised.add("clean")

    report.add(check_command_coverage(jsat_bin, env, exercised))
