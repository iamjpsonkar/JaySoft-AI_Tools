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
import shutil
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
    make_recorder,
    read_recordings,
    run_cli,
    timed,
)
from ..fixtures import scratch_facts

# Commands that are inherently interactive (they exec an unattached REPL or a
# GUI tool and the only honest substitution is not feasible) and so are
# verified via --help plus their side effects rather than by running them bare.
# Everything else that used to hide here — shell, gpt, ollama, claude, codex,
# opencode, cursor, windsurf, zed, gemini — now has a REAL exercised check:
# the REPL trio runs through jsat's own piped (non-TTY) stdin mode, and the
# launchers run through a PATH recorder stub.
INTERACTIVE = {"bob"}

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
def check_lifecycle_restart_resume(jsat_bin: str, env: dict[str, str], tmp: Path,
                                   repo: Path) -> Check:
    """restart and resume against the real runtime record.

    `jsat start` runs in the foreground, so each stage is driven as a
    background process here, and the same sleeping recorder stub stands in for
    claude throughout. The record file in JSAT_RUNTIME_DIR is what makes
    `restart` and `resume` know the previous `via`, so all three stages share
    one runtime dir — exactly the real usage.
    """
    stub_dir = tmp / "stub-lifecycle-rr"
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
    home = tmp / "lifecycle-rr-home"
    home.mkdir(parents=True, exist_ok=True)
    runtime = tmp / "lifecycle-rr-runtime"
    scoped = {**env,
              "PATH": f"{stub_dir}{os.pathsep}{env.get('PATH', '')}",
              "HOME": str(home),
              "JSAT_RUNTIME_DIR": str(runtime)}

    held: list[subprocess.Popen[str]] = []

    def wait_for(n: int, proc: subprocess.Popen[str]) -> list[dict]:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            recs = read_recordings(log)
            if len(recs) >= n:
                return recs
            if proc.poll() is not None:
                out, err = proc.communicate(timeout=10)
                raise AssertionError(
                    f"jsat exited (rc={proc.returncode}) before {n} invocation(s)\n"
                    f"out={out[-400:]} err={err[-400:]}"
                )
            time.sleep(0.5)
        raise AssertionError(f"never saw {n} stub invocation(s)")

    def gone(pid: int) -> bool:
        for _ in range(40):
            if not Path(f"/proc/{pid}").exists():
                return True
            time.sleep(0.25)
        return False

    def stop() -> tuple[int, str]:
        s = run_cli(jsat_bin, ["stop", "claude"], scoped, cwd=str(repo), timeout=90)
        return s.returncode, (s.stdout + s.stderr)[:200]

    try:
        pids: list[int] = []
        argv_by_stage: list[list[str]] = []

        for stage in ("start", "restart", "resume"):
            proc = subprocess.Popen(
                [jsat_bin, stage, "claude", "--repo", str(repo)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                env=scoped, cwd=str(repo),
            )
            held.append(proc)
            recs = wait_for(len(pids) + 1, proc)
            pids.append(recs[-1].get("pid"))
            argv_by_stage.append(recs[-1].get("argv", []))
            rc, text = stop()
            if rc != 0:
                return Check("cli_lifecycle_restart_resume", "cli_lifecycle",
                             FAIL, f"{stage}: jsat stop rc={rc}",
                             detail=text)
            if not gone(pids[-1]):
                return Check("cli_lifecycle_restart_resume", "cli_lifecycle",
                             FAIL, f"{stage}: the tracked pid {pids[-1]} "
                                   "survived `jsat stop`")

        problems = []
        if len(pids) != 3:
            problems.append(f"expected 3 invocations, saw {len(pids)}")
        if pids[0] == pids[1]:
            problems.append("restart reused the pre-stop pid")
        if argv_by_stage[1] != [str(stub)]:
            problems.append(f"restart passed unexpected argv: {argv_by_stage[1]!r}")
        if not argv_by_stage[2] or "-continue" not in argv_by_stage[2][-1]:
            problems.append("resume did not pass claude's --continue flag")
        if problems:
            return Check("cli_lifecycle_restart_resume", "cli_lifecycle", FAIL,
                         "; ".join(problems),
                         detail=f"pids={pids} argv={argv_by_stage}")
        return Check("cli_lifecycle_restart_resume", "cli_lifecycle", PASS,
                     "start→stop→restart→stop→resume→stop all tracked a fresh "
                     "real process from the shared runtime record")
    finally:
        for proc in held:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()


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


# ── The REPL trio: shell, gpt, ollama, driven through piped stdin ─────────
#
# JSATShell.run() reads line-by-line from stdin when stdin is not a TTY, so
# these commands — which normally open an interactive prompt — can be
# exercised for real without a pty. The index they read was just rebuilt by
# check_analysis_commands ("Nodes:" in the output is the proof the command
# really dispatched, not the Typer help table).

@timed
def check_shell_piped(jsat_bin: str, env: dict[str, str], repo: Path) -> Check:
    r = run_cli(jsat_bin, ["shell", "--repo", str(repo)], env, cwd=str(repo),
                timeout=90, stdin_text="help\nstatus\nquit\nexit\n")
    if r.returncode == 0 and "Nodes:" in r.stdout and "blast-radius" in r.stdout:
        return Check("cli_shell", "cli", PASS,
                     "jsat shell executed real commands over piped stdin",
                     detail=r.stdout.strip()[:400])
    return Check("cli_shell", "cli", FAIL,
                 "jsat shell did not dispatch commands in piped (non-TTY) mode",
                 detail=f"rc={r.returncode} out={r.stdout[:300]} "
                        f"err={r.stderr[:300]}",
                 remediation="fall back to the piped loop in "
                             "jsat/tools/shell.py::JSATShell.run")


@timed
def check_gpt_shell(jsat_bin: str, env: dict[str, str], repo: Path) -> Check:
    """jsat gpt without an API key must still start the JSAT shell rather than
    hang on a prompt or fail loudly — that is the documented degrade path."""
    no_key = {k: v for k, v in env.items() if not k.startswith("OPENAI_")}
    r = run_cli(jsat_bin, ["gpt", "--repo", str(repo)], no_key, cwd=str(repo),
                timeout=90, stdin_text="status\nquit\nexit\n")
    if r.returncode == 0 and "Nodes:" in r.stdout:
        return Check("cli_gpt", "cli", PASS,
                     "jsat gpt started the JSAT shell without an API key",
                     detail=r.stdout.strip()[:300])
    return Check("cli_gpt", "cli", FAIL,
                 "jsat gpt failed to degrade to the JSAT shell without a key",
                 detail=f"rc={r.returncode} out={r.stdout[:300]} "
                        f"err={r.stderr[:300]}")


@timed
def check_ollama_direct_model(jsat_bin: str, env: dict[str, str],
                              repo: Path) -> Check:
    """jsat ollama --model <m> opens the shell with that model selected — the
    direct path that needs no `ollama` binary and no network."""
    r = run_cli(jsat_bin, ["ollama", "-m", "selftest-model", "--repo", str(repo)],
                env, cwd=str(repo), timeout=90,
                stdin_text="status\nquit\nexit\n")
    if r.returncode == 0 and "Nodes:" in r.stdout:
        return Check("cli_ollama", "cli", PASS,
                     "jsat ollama --model launched the shell with the model selected",
                     detail=r.stdout.strip()[:300])
    return Check("cli_ollama", "cli", FAIL,
                 "jsat ollama --model did not reach the JSAT shell",
                 detail=f"rc={r.returncode} out={r.stdout[:300]} "
                        f"err={r.stderr[:300]}")


@timed
def check_ollama_tool_delegation(jsat_bin: str, env: dict[str, str], tmp: Path,
                                 repo: Path) -> Check:
    """jsat ollama --tool <t> -m <m> --yes must delegate to the REAL ollama CLI
    with a `launch` command that matches Ollama's documented contract."""
    stub_dir = tmp / "stub-ollama"
    stub_dir.mkdir(parents=True, exist_ok=True)
    log = stub_dir / "argv.jsonl"
    stub = stub_dir / "ollama"
    make_recorder(stub, log)
    scoped = {**env, "PATH": f"{stub_dir}{os.pathsep}{env.get('PATH', '')}",
              "HOME": str(tmp / "ollama-delegation-home")}
    r = run_cli(jsat_bin, ["ollama", "--tool", "claude", "-m", "selftest-model",
                           "--yes", "--repo", str(repo)],
                scoped, cwd=str(repo), timeout=120)
    recs = read_recordings(log)
    if not recs:
        return Check("cli_ollama_tool", "cli", FAIL,
                     "jsat ollama --tool never invoked the ollama CLI",
                     detail=f"rc={r.returncode} out={r.stdout[-400:]} "
                            f"err={r.stderr[-400:]}")
    argv = recs[0]["argv"]
    wanted = ["launch", "claude", "--model", "selftest-model", "--yes"]
    if argv[1:] != wanted:
        return Check("cli_ollama_tool", "cli", FAIL,
                     "jsat ollama --tool built the wrong ollama launch command",
                     detail=f"argv={argv[1:]!r} wanted={wanted!r}",
                     remediation="check build_ollama_launch_args in "
                                 "jsat/_ollama.py against Ollama's launch contract")
    return Check("cli_ollama_tool", "cli", PASS,
                 "jsat ollama --tool delegated to `ollama launch` with the "
                 "expected model flags")


@timed
def check_ollama_missing_binary(jsat_bin: str, env: dict[str, str],
                                tmp: Path) -> Check:
    """With no `ollama` on PATH, a --tool invocations must refuse cleanly with
    install guidance — exit 1 and a hint, never a raw traceback."""
    no_ollama = [d for d in env.get("PATH", "").split(os.pathsep)
                 if d and not Path(d).joinpath("ollama").exists()]
    filtered = os.pathsep.join(no_ollama) or "/usr/bin:/bin"
    scoped = {**env, "PATH": filtered, "HOME": str(tmp / "ollama-missing-home")}
    if shutil.which("ollama", path=filtered):
        return Check("cli_ollama_missing", "cli", UNAVAILABLE,
                     "a real `ollama` binary could not be hidden from PATH, so "
                     "the absent-binary path cannot be forced here")
    r = run_cli(jsat_bin, ["ollama", "--tool", "claude", "-m", "selftest-model",
                           "--yes"], scoped, cwd=str(tmp), timeout=60)
    text = r.stdout + r.stderr
    if r.returncode != 0 and "ollama not found in PATH" in text:
        return Check("cli_ollama_missing", "cli", PASS,
                     "jsat ollama --tool refused cleanly when ollama is absent",
                     detail=text.strip()[-300:])
    return Check("cli_ollama_missing", "cli", FAIL,
                 "expected exit 1 + 'ollama not found in PATH' guidance",
                 detail=f"rc={r.returncode} {text[:400]}")


@timed
def check_session_roundtrip(jsat_bin: str, env: dict[str, str],
                            tmp: Path) -> Check:
    """session list/show/resume/rm/prune against a REAL file in the documented
    on-disk format (frontmatter + ## Steps + ## Findings), under its own
    sessions dir so no other suite's artifacts interfere."""
    root = tmp / "sessions-roundtrip"
    root.mkdir(parents=True, exist_ok=True)
    scoped = {**env, "JSAT_SESSIONS_DIR": str(root)}

    def session(skill: str, task: str, status: str, steps: str,
                created: str, mtime: float) -> Path:
        p = root / f"{skill}-{created}.md"
        p.write_text(
            f"---\nskill: {skill}\ntask: {task}\ncreated: 2026-09-05T09:00:00Z\n"
            f"status: {status}\n---\n\n## Steps\n{steps}\n\n## Findings\n"
            f"**f1:** a finding\n"
        )
        os.utime(p, (mtime, mtime))
        return p

    file1 = session("magic", "fix retry logic", "in_progress",
                    "- [x] status (finding: 1307 nodes)\n- [ ] blast-radius",
                    "20260905-1000", 1_700_000_000.0)
    lst = run_cli(jsat_bin, ["session", "list"], scoped, cwd=str(tmp), timeout=60)
    if file1.name not in lst.stdout or "magic" not in lst.stdout:
        return Check("cli_session_roundtrip", "cli", FAIL,
                     "session list did not show the file just written",
                     detail=lst.stdout[-400:] + lst.stderr[-200:])
    show = run_cli(jsat_bin, ["session", "show", file1.name], scoped,
                   cwd=str(tmp), timeout=60)
    if "blast-radius" not in show.stdout:
        return Check("cli_session_roundtrip", "cli", FAIL,
                     "session show did not render the pending step",
                     detail=show.stdout[-400:])
    resume = run_cli(jsat_bin, ["session", "resume", file1.name], scoped,
                     cwd=str(tmp), timeout=60)
    if "Next step: blast-radius" not in resume.stdout:
        return Check("cli_session_roundtrip", "cli", FAIL,
                     "session resume did not point at the first incomplete step",
                     detail=resume.stdout[-400:])
    rm = run_cli(jsat_bin, ["session", "rm", file1.name], scoped,
                 cwd=str(tmp), timeout=60)
    if file1.exists():
        return Check("cli_session_roundtrip", "cli", FAIL,
                     "session rm left the file on disk",
                     detail=rm.stdout[-300:] + rm.stderr[-300:])

    # prune --keep 1 must delete the OLD, COMPLETED session and retain the
    # newest in_progress one.
    completed_old = session("crack", "db schema", "completed",
                            "- [x] a", "20260905-0900", 1_000_000_000.0)
    inprog_new = session("magic", "second task", "in_progress",
                         "- [ ] b", "20260905-1100", 2_000_000_000.0)
    prune = run_cli(jsat_bin, ["session", "prune", "--keep", "1"], scoped,
                    cwd=str(tmp), timeout=60)
    problems = []
    if completed_old.exists():
        problems.append("prune --keep 1 left the old completed session behind")
    if not inprog_new.exists():
        problems.append("prune --keep 1 deleted the newest in_progress session")
    if prune.returncode != 0:
        problems.append(f"session prune rc={prune.returncode}")
    if problems:
        return Check("cli_session_roundtrip", "cli", FAIL, "; ".join(problems),
                     detail=f"files={sorted(p.name for p in root.glob('*.md'))}")
    return Check("cli_session_roundtrip", "cli", PASS,
                 "session list/show/resume/rm/prune round-tripped a real "
                 "documented-format session file")


@timed
def check_skills_run(jsat_bin: str, env: dict[str, str], tmp: Path) -> Check:
    """skills list + run against a REAL YAML manifest with a script source —
    exercising the dormant skills registry's only executed path."""
    skills_fx = tmp / "skills-fixture"
    skills_fx.mkdir(parents=True, exist_ok=True)
    script = skills_fx / "run.sh"
    script.write_text("#!/bin/sh\necho fixture-skill-ran\n")
    script.chmod(0o755)
    (skills_fx / "fixture.yaml").write_text(
        f"name: fixture-skill\nversion: 0.1.0\n"
        f"description: a selftest script skill\n"
        f"source:\n  type: script\n  path: {script}\n"
    )
    cfg = tmp / "jsat-selftest-config.yaml"
    cfg.write_text(f"version: '1'\nskills:\n  dir: {skills_fx}\n")
    scoped = {**env, "JSAT_CONFIG": str(cfg)}

    lst = run_cli(jsat_bin, ["skills", "list"], scoped, cwd=str(tmp), timeout=60)
    if "fixture-skill" not in lst.stdout or "script" not in lst.stdout:
        return Check("cli_skills_run", "cli", FAIL,
                     "skills list did not show the fixture manifest",
                     detail=lst.stdout[-400:] + lst.stderr[-200:])
    ran = run_cli(jsat_bin, ["skills", "run", "fixture-skill"], scoped,
                  cwd=str(tmp), timeout=90)
    if "fixture-skill-ran" not in ran.stdout:
        return Check("cli_skills_run", "cli", FAIL,
                     "skills run did not execute the script source",
                     detail=f"rc={ran.returncode} out={ran.stdout[:400]} "
                            f"err={ran.stderr[:400]}")
    missing = run_cli(jsat_bin, ["skills", "run", "does-not-exist"], scoped,
                      cwd=str(tmp), timeout=60)
    if missing.returncode == 0 or "failed" not in (missing.stdout + missing.stderr).lower():
        return Check("cli_skills_run", "cli", FAIL,
                     "skills run on an unknown skill did not fail cleanly",
                     detail=f"rc={missing.returncode} "
                            f"{missing.stdout[:300]}{missing.stderr[:300]}")
    return Check("cli_skills_run", "cli", PASS,
                 "skills list showed the manifest, run executed its script, "
                 "and an unknown skill failed gracefully")


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

    # The piped-REPL trio reads the graph index check_analysis_commands just
    # rebuilt, so it must stay after it.
    report.add(check_shell_piped(jsat_bin, env, repo)); exercised.add("shell")
    report.add(check_gpt_shell(jsat_bin, env, repo)); exercised.add("gpt")
    report.add(check_ollama_direct_model(jsat_bin, env, repo))
    exercised.add("ollama")
    report.add(check_ollama_tool_delegation(jsat_bin, env, tmp, repo))
    report.add(check_ollama_missing_binary(jsat_bin, env, tmp))
    report.add(check_session_roundtrip(jsat_bin, env, tmp))
    exercised.add("session")
    report.add(check_skills_run(jsat_bin, env, tmp))
    exercised.add("skills")

    for command, target in LAUNCHER_MATRIX.items():
        report.add(check_launcher(jsat_bin, env, tmp, repo, command, target))
        exercised.add(command)

    report.add(check_lifecycle_start_ps_stop(jsat_bin, env, tmp, repo))
    exercised |= {"start", "stop", "ps"}
    report.add(check_pid_reuse_guard(tmp))
    report.add(check_lifecycle_restart_resume(jsat_bin, env, tmp, repo))
    exercised |= {"restart", "resume"}

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
