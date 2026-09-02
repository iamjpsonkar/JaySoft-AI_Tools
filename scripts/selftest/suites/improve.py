"""
Phase I — the self-improvement subsystem and its privacy invariant.

AGENTS.md §8 calls this the invariant that must not break: JSAT records
friction in *itself* while running on users' private codebases, so a leak
here exfiltrates someone's proprietary source. Nothing tested it end to end
against a real crash before.

The important design property is "drop, never redact": a record that cannot
be proven free of user data is discarded whole. So the checks below do not
ask `verify_clean` whether the output is clean — that is the code under
test. They scan the stored bytes independently for absolute paths, the
machine's home directory, its username, its cwd, and the literal value of
every environment variable.
"""
from __future__ import annotations

import getpass
import hashlib
import json
import os
from pathlib import Path

from ..core import FAIL, PASS, UNAVAILABLE, Check, Report, run_cli, timed


def _tree_hash(root: Path) -> str:
    """Hash every .py under a tree, so tampering is detectable."""
    h = hashlib.sha256()
    for p in sorted(root.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        h.update(p.relative_to(root).as_posix().encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def _leak_markers() -> dict[str, str]:
    """Strings that must never appear in a stored signal."""
    markers = {
        "home directory": str(Path.home()),
        "cwd": os.getcwd(),
    }
    try:
        markers["username"] = getpass.getuser()
    except Exception:
        pass
    return {k: v for k, v in markers.items() if v and len(v) > 3}


@timed
def check_signal_recorded(tmp: Path) -> Check:
    """A real exception recorded through the real capture path."""
    improve_dir = tmp / "improve-isolated"
    os.environ["JSAT_IMPROVE_DIR"] = str(improve_dir)
    from jsat._improve import flush, read_clusters, record_signal
    try:
        raise ValueError("Graph query failed: something went wrong in a tool")
    except ValueError as e:
        record_signal(kind="crash", source="selftest",
                      exc=e, op="selftest_operation")
    flush()
    signals = improve_dir / "signals.jsonl"
    if not signals.exists():
        return Check("improve_signal_recorded", "improve", FAIL,
                     "a real recorded crash produced no signals.jsonl",
                     detail=f"improve_dir={improve_dir} "
                            f"contents={list(improve_dir.rglob('*')) if improve_dir.exists() else 'absent'}",
                     remediation="check _capture.record_signal's flush path")
    clusters = read_clusters()
    return Check("improve_signal_recorded", "improve", PASS,
                 f"a real crash was captured into an isolated store "
                 f"({len(clusters)} cluster(s))",
                 detail=signals.read_text()[:300])


@timed
def check_no_leak_in_store(tmp: Path) -> Check:
    """Independently scan the stored signal bytes for user data."""
    improve_dir = Path(os.environ.get("JSAT_IMPROVE_DIR", tmp / "improve-isolated"))
    signals = improve_dir / "signals.jsonl"
    if not signals.exists():
        return Check("improve_no_leak", "improve", UNAVAILABLE,
                     "no signals.jsonl to inspect")
    blob = signals.read_text()
    for name, marker in _leak_markers().items():
        if marker in blob:
            return Check("improve_no_leak", "improve", FAIL,
                         f"the stored signal contains this machine's {name}",
                         detail=f"marker={marker!r} found in signals.jsonl",
                         remediation="tighten jsat/_improve/_sanitize.py")
    # Any absolute-looking path at all is a leak: package-relative frames are
    # the only path shape the sanitizer is allowed to keep.
    import re
    for m in re.finditer(r'"[^"]*(?:/home/|/Users/|[A-Za-z]:\\\\)[^"]*"', blob):
        return Check("improve_no_leak", "improve", FAIL,
                     "the stored signal contains an absolute filesystem path",
                     detail=m.group(0)[:200])
    # Environment variable VALUES (tokens, keys, hostnames) must not appear.
    for key, value in os.environ.items():
        if len(value) >= 8 and value in blob and key not in ("PWD", "OLDPWD"):
            return Check("improve_no_leak", "improve", FAIL,
                         f"the stored signal contains the value of ${key}",
                         detail=f"${key} value appears verbatim")
    return Check("improve_no_leak", "improve", PASS,
                 "an independent scan of the stored signal found no home dir, "
                 "username, cwd, absolute path, or env-var value")


@timed
def check_drop_never_redact() -> Check:
    """A record that cannot be made safe must be dropped, not scrubbed."""
    from jsat._improve._sanitize import build_record, verify_clean
    home = str(Path.home())
    poisoned = {
        "note": f"failed reading {home}/secret-project/src/private.py",
        "token": "AKIA" + "EXAMPLE" + "0NOTREAL9",
    }
    if verify_clean(poisoned):
        return Check("improve_drop_never_redact", "improve", FAIL,
                     "verify_clean() approved a payload containing this "
                     "machine's home directory and an AWS-shaped key",
                     remediation="jsat/_improve/_sanitize.py::verify_clean")
    # And a record built from a poisoned detail dict must come back as None
    # (dropped) or provably clean — never partially redacted.
    try:
        raise RuntimeError(f"cannot open {home}/private/thing.py")
    except RuntimeError as e:
        rec = build_record(kind="crash", source="selftest", exc=e,
                           op="selftest", detail=poisoned)
    if rec is None:
        return Check("improve_drop_never_redact", "improve", PASS,
                     "a poisoned record was dropped entirely rather than "
                     "redacted, and verify_clean rejected the raw payload")
    blob = json.dumps(rec)
    if home in blob or "AKIA" in blob:
        return Check("improve_drop_never_redact", "improve", FAIL,
                     "build_record kept user data from a poisoned detail dict",
                     detail=blob[:300])
    return Check("improve_drop_never_redact", "improve", PASS,
                 "verify_clean rejected the poisoned payload and build_record "
                 "emitted a record free of it",
                 detail=blob[:250])


@timed
def check_exception_message_not_stored() -> Check:
    """Exception *messages* interpolate user paths, so only an allowlisted
    prefix may survive — never str(exc)."""
    from jsat._improve._sanitize import build_record
    secret = "svc-acme-billing-internal-name"
    try:
        raise ValueError(f"Unsupported language in {secret}/module.py")
    except ValueError as e:
        rec = build_record(kind="crash", source="selftest", exc=e, op="selftest")
    if rec is None:
        return Check("improve_no_exc_message", "improve", PASS,
                     "the record was dropped rather than store an "
                     "unrecognised exception message")
    blob = json.dumps(rec)
    if secret in blob:
        return Check("improve_no_exc_message", "improve", FAIL,
                     "a raw exception message containing a private identifier "
                     "was stored",
                     detail=blob[:300],
                     remediation="only _MESSAGE_PREFIXES matches may be kept")
    return Check("improve_no_exc_message", "improve", PASS,
                 "the exception type was kept but the interpolated message was "
                 "not stored",
                 detail=blob[:250])


@timed
def check_store_refuses_escape(tmp: Path) -> Check:
    """_safe_write is the structural reason JSAT cannot patch its own source."""
    from jsat._improve._store import _safe_write
    target = Path.home() / ".jsat-selftest-escape-canary"
    try:
        _safe_write(target, "should never be written")
    except Exception:
        if target.exists():
            target.unlink(missing_ok=True)
            return Check("improve_safe_write_guard", "improve", FAIL,
                         "_safe_write raised but still created the file")
        return Check("improve_safe_write_guard", "improve", PASS,
                     "_safe_write refused a target outside the improve store")
    existed = target.exists()
    target.unlink(missing_ok=True)
    if existed:
        return Check("improve_safe_write_guard", "improve", FAIL,
                     "_safe_write wrote OUTSIDE the improve store — JSAT could "
                     "patch arbitrary files",
                     detail=str(target),
                     remediation="jsat/_improve/_store.py::_safe_write")
    return Check("improve_safe_write_guard", "improve", PASS,
                 "_safe_write did not create a file outside the improve store")


@timed
def check_improve_cli(jsat_bin: str, repo: Path, tmp: Path,
                      allow_llm: bool) -> Check:
    """`jsat improve` end to end, proving it never patches installed source."""
    improve_dir = tmp / "improve-cli"
    env = {**os.environ,
           "JSAT_IMPROVE_DIR": str(improve_dir),
           "JSAT_DATA_DIR": str(tmp / "improve-cli-data"),
           "JSAT_SESSIONS_DIR": str(tmp / "improve-cli-sessions")}
    import jsat
    pkg_root = Path(jsat.__file__).resolve().parent
    before = _tree_hash(pkg_root)
    r = run_cli(jsat_bin, ["improve"], env, cwd=str(repo), timeout=600)
    after = _tree_hash(pkg_root)
    if before != after:
        return Check("improve_cli", "improve", FAIL,
                     "`jsat improve` MODIFIED the installed jsat package — it "
                     "must never patch its own source",
                     detail=f"tree hash {before[:12]} → {after[:12]}",
                     remediation="all writes must go through _store._safe_write")
    if r.returncode != 0:
        return Check("improve_cli", "improve", FAIL,
                     "`jsat improve` exited non-zero",
                     detail=f"rc={r.returncode} out={r.stdout[-300:]} "
                            f"err={r.stderr[-300:]}")
    return Check("improve_cli", "improve", PASS,
                 "`jsat improve` ran and left the installed package "
                 "byte-identical",
                 detail=r.stdout.strip()[-300:])


@timed
def check_improve_submit_refuses_foreign_repo(repo: Path) -> Check:
    """The maintainer-only path must refuse a repo that is not JSAT."""
    try:
        from jsat.tools import improve_submit
    except Exception as e:
        return Check("improve_submit_guard", "improve", UNAVAILABLE,
                     f"could not import improve_submit: {e}")
    guard = getattr(improve_submit, "_guard_is_jsat_repo", None)
    if guard is None:
        return Check("improve_submit_guard", "improve", UNAVAILABLE,
                     "improve_submit has no _guard_is_jsat_repo to exercise")
    # The fixture repo has a real git dir and is emphatically not JSAT.
    try:
        result = guard(repo)
        refused = result is False
    except Exception:
        refused = True
    if not refused:
        return Check("improve_submit_guard", "improve", FAIL,
                     "improve_submit's guard accepted a non-JSAT git repo, so "
                     "an AI-generated patch could be applied to a user's own "
                     "project",
                     remediation="jsat/tools/improve_submit.py::_guard_is_jsat_repo")
    return Check("improve_submit_guard", "improve", PASS,
                 "improve_submit refuses to operate on a repo that is not JSAT")


@timed
def check_opt_out_gates(tmp: Path) -> Check:
    """The three documented ways to turn telemetry off must all work.

    Note the division of labour, which is easy to misread: set_mode("mcp")
    suppresses the *nudge* (so it can never pollute MCP stdio or a piped
    --json), while capture itself is gated by JSAT_NO_IMPROVE and CI. All
    three are opt-out promises made in the README, so all three are asserted.
    """
    from jsat._improve import _capture, set_mode
    prior_mode = _capture._MODE
    prior_no_improve = os.environ.get("JSAT_NO_IMPROVE")
    prior_ci = os.environ.get("CI")
    problems = []
    try:
        os.environ.pop("JSAT_NO_IMPROVE", None)
        os.environ.pop("CI", None)

        if _capture._capture_disabled():
            problems.append("capture reported disabled with no opt-out set")

        os.environ["JSAT_NO_IMPROVE"] = "1"
        if not _capture._capture_disabled():
            problems.append("JSAT_NO_IMPROVE=1 did not disable capture")
        os.environ.pop("JSAT_NO_IMPROVE", None)

        os.environ["CI"] = "true"
        if not _capture._capture_disabled():
            problems.append("CI=true did not disable capture")
        os.environ.pop("CI", None)

        # The nudge is what must never reach MCP stdio.
        set_mode("mcp")
        src = __import__("inspect").getsource(_capture._maybe_nudge)
        if '_MODE == "mcp"' not in src:
            problems.append("_maybe_nudge no longer short-circuits in mcp mode")
    finally:
        _capture._MODE = prior_mode
        if prior_no_improve is None:
            os.environ.pop("JSAT_NO_IMPROVE", None)
        else:
            os.environ["JSAT_NO_IMPROVE"] = prior_no_improve
        if prior_ci is None:
            os.environ.pop("CI", None)
        else:
            os.environ["CI"] = prior_ci

    if problems:
        return Check("improve_opt_out_gates", "improve", FAIL,
                     f"{len(problems)} opt-out gate(s) do not work",
                     detail="; ".join(problems),
                     remediation="jsat/_improve/_capture.py")
    return Check("improve_opt_out_gates", "improve", PASS,
                 "JSAT_NO_IMPROVE and CI both disable capture, and the nudge "
                 "short-circuits in mcp mode so it cannot reach MCP stdio")


@timed
def check_nudge_never_pollutes_json(jsat_bin: str, repo: Path,
                                    tmp: Path) -> Check:
    """`doctor --json` must stay machine-readable even with clusters present.

    The nudge writes to stderr behind a dual-TTY check; this asserts the
    observable contract a caller depends on rather than the mechanism.
    """
    improve_dir = tmp / "improve-nudge"
    improve_dir.mkdir(parents=True, exist_ok=True)
    # Plant enough clusters to cross any nudge threshold.
    (improve_dir / "clusters.json").write_text(json.dumps({
        "abc123def456": {"kind": "crash", "count": 99, "source": "selftest",
                          "exc_type": "ValueError", "op": "selftest",
                          "first_seen": "2026-01-01T00:00:00Z",
                          "last_seen": "2026-01-01T00:00:00Z"}
    }))
    env = {**os.environ,
           "JSAT_IMPROVE_DIR": str(improve_dir),
           "JSAT_DATA_DIR": str(tmp / "nudge-data"),
           "JSAT_SESSIONS_DIR": str(tmp / "nudge-sessions")}
    r = run_cli(jsat_bin, ["doctor", "--json"], env, cwd=str(repo), timeout=90)
    try:
        json.loads(r.stdout)
    except json.JSONDecodeError as e:
        return Check("improve_nudge_json_safe", "improve", FAIL,
                     f"doctor --json stdout was not parseable with improve "
                     f"clusters present: {e}",
                     detail=r.stdout[:400],
                     remediation="the nudge or a log line is reaching stdout")
    return Check("improve_nudge_json_safe", "improve", PASS,
                 "doctor --json stayed machine-readable with 99 pending "
                 "improve signals on disk")


def run(report: Report, jsat_bin: str, repo: Path, tmp: Path, *,
        allow_llm: bool) -> None:
    report.add(check_signal_recorded(tmp))
    report.add(check_no_leak_in_store(tmp))
    report.add(check_drop_never_redact())
    report.add(check_exception_message_not_stored())
    report.add(check_store_refuses_escape(tmp))
    report.add(check_improve_submit_refuses_foreign_repo(repo))
    report.add(check_opt_out_gates(tmp))
    report.add(check_nudge_never_pollutes_json(jsat_bin, repo, tmp))
    report.add(check_improve_cli(jsat_bin, repo, tmp, allow_llm))
