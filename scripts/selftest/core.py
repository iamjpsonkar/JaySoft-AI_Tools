"""
Shared plumbing for the JSAT self-test suites.

Everything in here is lifted from the original single-file
`scripts/jsat_selftest.py` and kept deliberately dependency-free (stdlib
only) so the harness can run against a bare `pip install jsat` with no dev
extras present.

The three-state discipline is the reason this report is trustworthy and must
not be relaxed:

  pass         the real artifact did the real thing
  fail         the real artifact did the wrong thing — a bug to fix
  unavailable  an external dependency genuinely is not on this machine

A missing dependency is NEVER a failure, and a check is never silently
skipped. Anything that cannot be classified into one of those three is a
`fail` by construction, because "we did not look" must not read as "fine".
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

PASS = "pass"
FAIL = "fail"
UNAVAILABLE = "unavailable"


@dataclass
class Check:
    id: str
    category: str
    status: str  # PASS | FAIL | UNAVAILABLE
    summary: str
    detail: str = ""
    remediation: str = ""
    elapsed_ms: int = 0


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)
    quiet: bool = False

    def add(self, c: Check) -> Check:
        self.checks.append(c)
        if not self.quiet:
            icon = {PASS: "✅", FAIL: "❌", UNAVAILABLE: "⚠️ "}[c.status]
            print(f"  {icon} [{c.category}] {c.id} — {c.summary}", flush=True)
        return c

    def ids(self) -> set[str]:
        return {c.id for c in self.checks}

    def tally(self) -> dict[str, int]:
        return {
            "total": len(self.checks),
            PASS: sum(1 for c in self.checks if c.status == PASS),
            FAIL: sum(1 for c in self.checks if c.status == FAIL),
            UNAVAILABLE: sum(1 for c in self.checks if c.status == UNAVAILABLE),
        }


def timed(fn: Callable[..., Check]) -> Callable[..., Check]:
    def wrapper(*a: Any, **kw: Any) -> Check:
        t0 = time.monotonic()
        try:
            c = fn(*a, **kw)
        except Exception as e:  # a crashing check is a failing check, never a lost one
            c = Check(getattr(fn, "__name__", "unknown_check"), "harness", FAIL,
                      f"check raised {type(e).__name__}: {e}")
        c.elapsed_ms = round((time.monotonic() - t0) * 1000)
        return c

    return wrapper


# ── Reachability probes ────────────────────────────────────────────────────

def tcp_reachable(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def http_reachable(url: str, timeout: float = 2.0) -> bool:
    try:
        urllib.request.urlopen(url, timeout=timeout)  # noqa: S310 (local/dev self-test)
        return True
    except Exception:
        return False


def http_get(url: str, timeout: float = 5.0) -> tuple[int, str]:
    """Return (status, body). Status 0 means the request never completed."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"


# ── Subprocess helpers ────────────────────────────────────────────────────

def run_cli(jsat_bin: str, args: list[str], env: dict[str, str],
            cwd: str | None = None, timeout: int = 60,
            stdin_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [jsat_bin, *args], capture_output=True, text=True, timeout=timeout,
        env=env, cwd=cwd, input=stdin_text,
    )


def resolve_jsat_binary() -> str | None:
    """Return the `jsat` console script installed in the SAME interpreter
    running this file, not whatever `jsat` happens to be first on $PATH.

    A bare `shutil.which("jsat")` can silently pick a different environment's
    copy than the one `sys.executable` belongs to (e.g. a stale conda-env
    install shadowing this repo's own .venv) — exactly the class of bug the
    editable-checkout check exists to catch. Resolving from sys.executable's
    own bin/ directory first keeps "which interpreter" and "which binary" the
    same answer, so this script always tests what it thinks it's testing.
    """
    same_env = Path(sys.executable).parent / "jsat"
    if same_env.exists():
        return str(same_env)
    return shutil.which("jsat")


def make_recorder(path: Path, log: Path, exit_code: int = 0,
                  stdout_text: str = "") -> Path:
    """Write an executable stub that records its argv+env and exits.

    Used to test JSAT's launcher and lifecycle commands end to end. Only the
    *third-party* binary JSAT spawns is substituted — every line of JSAT code
    under test is the real thing, and the assertion is made against the real
    argv and the real generated --mcp-config file. This is the honest way to
    verify a command whose whole job is "exec another tool correctly".
    """
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys, pathlib\n"
        f"log = pathlib.Path({str(log)!r})\n"
        "rec = {'argv': sys.argv, 'cwd': os.getcwd(),\n"
        "       'env': {k: v for k, v in os.environ.items()\n"
        "               if k.startswith(('JSAT_', 'ANTHROPIC_', 'OPENCODE_', 'OPENAI_'))}}\n"
        "with log.open('a') as f:\n"
        "    f.write(json.dumps(rec) + '\\n')\n"
        f"sys.stdout.write({stdout_text!r})\n"
        f"sys.exit({exit_code})\n"
    )
    path.chmod(0o755)
    return path


def make_config_capturing_recorder(path: Path, log: Path) -> Path:
    """Like make_recorder, but also snapshots any --mcp-config file contents.

    JSAT hands its launchers a NamedTemporaryFile and unlinks it once the
    child exits, so the config can only be read from inside the child. Its
    contents are recorded under "configs" keyed by the path as passed.
    """
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys, pathlib\n"
        f"log = pathlib.Path({str(log)!r})\n"
        "configs = {}\n"
        "for i, a in enumerate(sys.argv):\n"
        "    if a in ('--mcp-config', '--mcp-config-file') and i + 1 < len(sys.argv):\n"
        "        raw = sys.argv[i + 1]\n"
        "        try:\n"
        "            configs[raw] = pathlib.Path(raw).read_text()\n"
        "        except OSError:\n"
        "            configs[raw] = raw\n"
        "rec = {'argv': sys.argv, 'cwd': os.getcwd(), 'configs': configs,\n"
        "       'env': {k: v for k, v in os.environ.items()\n"
        "               if k.startswith(('JSAT_', 'ANTHROPIC_', 'OPENCODE_', 'OPENAI_'))}}\n"
        "with log.open('a') as f:\n"
        "    f.write(json.dumps(rec) + '\\n')\n"
        "sys.exit(0)\n"
    )
    path.chmod(0o755)
    return path


def read_recordings(log: Path) -> list[dict[str, Any]]:
    if not log.exists():
        return []
    out = []
    for line in log.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


# ── Real MCP stdio client (JSON-RPC 2.0) ──────────────────────────────────

class MCPClient:
    """Drives `jsat mcp-server` over real stdin/stdout JSON-RPC.

    Non-JSON output on stdout is treated as a protocol violation and raised,
    not skipped: server.py's own contract is that stdout carries ONLY
    JSON-RPC, so a stray print() there is a real bug that breaks every AI
    client, and this is the only place it can be caught.
    """

    def __init__(self, jsat_bin: str, repo: Path | str, env: dict[str, str]):
        self.proc = subprocess.Popen(
            [jsat_bin, "mcp-server", "--repo", str(repo)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, env=env,
        )
        self._id = 0
        self.notifications: list[dict[str, Any]] = []

    def call(self, method: str, params: dict[str, Any] | None = None,
             timeout: float = 30.0) -> dict[str, Any] | None:
        self._id += 1
        req = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}}
        assert self.proc.stdin is not None and self.proc.stdout is not None
        self.proc.stdin.write(json.dumps(req) + "\n")
        self.proc.stdin.flush()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self.proc.stdout.readline()
            if not line:
                if self.proc.poll() is not None:
                    return None
                continue
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                raise RuntimeError(
                    f"non-JSON-RPC line on stdout (protocol violation): {line[:200]}"
                ) from None
            if "id" not in msg and "method" in msg:
                # server-initiated notification (e.g. notifications/progress)
                self.notifications.append(msg)
                continue
            if msg.get("id") == req["id"]:
                return msg
        return None

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        assert self.proc.stdin is not None
        note = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        self.proc.stdin.write(json.dumps(note) + "\n")
        self.proc.stdin.flush()

    def handshake(self) -> dict[str, Any] | None:
        resp = self.call("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "jsat_selftest", "version": "1.0"},
        })
        self.notify("notifications/initialized")
        return resp

    def tool(self, name: str, arguments: dict[str, Any] | None = None,
             timeout: float = 60.0) -> dict[str, Any] | None:
        return self.call("tools/call", {"name": name, "arguments": arguments or {}},
                         timeout=timeout)

    def stderr_tail(self, n: int = 600) -> str:
        """Best-effort stderr, without ever blocking.

        A plain `.read(n)` on a live child's pipe blocks until n bytes or EOF,
        and its only caller runs exactly when the server failed to answer
        `initialize` — so a server that hung after emitting a little stderr
        hung the whole self-test, and no report was ever written. Terminate
        first, then drain with a timeout.
        """
        if not self.proc.stderr:
            return ""
        try:
            if self.proc.poll() is None:
                self.proc.terminate()
            _out, errs = self.proc.communicate(timeout=5)
            return (errs or "")[-n:]
        except subprocess.TimeoutExpired:
            self.proc.kill()
            try:
                _out, errs = self.proc.communicate(timeout=5)
                return (errs or "")[-n:]
            except Exception:
                return "(stderr unavailable: server did not exit)"
        except Exception as e:
            return f"(stderr unavailable: {type(e).__name__})"

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()

    def __enter__(self) -> MCPClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def tool_text(resp: dict[str, Any] | None) -> str:
    """Flatten an MCP tools/call result into searchable text."""
    if not resp or "result" not in resp:
        return ""
    result = resp["result"]
    if isinstance(result, dict):
        content = result.get("content")
        if isinstance(content, list):
            parts = [c.get("text", "") for c in content if isinstance(c, dict)]
            if parts:
                return "\n".join(parts)
        return json.dumps(result)
    return str(result)


# ── Report writers ────────────────────────────────────────────────────────

def write_reports(report: Report, out_prefix: Path,
                  meta: dict[str, Any] | None = None) -> tuple[Path, Path]:
    json_path = out_prefix.with_suffix(".json")
    md_path = out_prefix.with_suffix(".md")
    tally = report.tally()

    by_cat: dict[str, dict[str, int]] = {}
    for c in report.checks:
        by_cat.setdefault(c.category, {PASS: 0, FAIL: 0, UNAVAILABLE: 0})[c.status] += 1

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo": str(REPO_ROOT),
        "meta": meta or {},
        "summary": tally,
        "by_category": by_cat,
        "checks": [c.__dict__ for c in report.checks],
    }
    json_path.write_text(json.dumps(payload, indent=2))

    lines = [
        "# JSAT Self-Test Report",
        "",
        f"Generated: {payload['generated_at']}",
        f"Repo: {payload['repo']}",
        "",
        f"**{tally[PASS]} passed / {tally[FAIL]} failed / "
        f"{tally[UNAVAILABLE]} unavailable** (of {tally['total']} checks)",
        "",
    ]
    if meta:
        lines += ["| Run parameter | Value |", "|---|---|"]
        lines += [f"| {k} | {v} |" for k, v in meta.items()]
        lines += [""]

    lines += ["## By category", "", "| Category | ✅ | ❌ | ⚠️ |", "|---|---|---|---|"]
    for cat in sorted(by_cat):
        s = by_cat[cat]
        lines += [f"| {cat} | {s[PASS]} | {s[FAIL]} | {s[UNAVAILABLE]} |"]
    lines += [""]

    if tally[FAIL]:
        lines += ["## ❌ Failures (fix these)", ""]
        for c in report.checks:
            if c.status == FAIL:
                lines += [f"### {c.id} ({c.category})", f"- {c.summary}"]
                if c.detail:
                    lines += ["```", c.detail[:1500], "```"]
                if c.remediation:
                    lines += [f"- **Fix:** {c.remediation}"]
                lines += [""]
    if tally[UNAVAILABLE]:
        lines += ["## ⚠️ Unavailable in this environment (not failures)", ""]
        for c in report.checks:
            if c.status == UNAVAILABLE:
                lines += [f"- **{c.id}** ({c.category}): {c.summary}"]
        lines += [""]
    lines += ["## ✅ Passed", ""]
    for c in report.checks:
        if c.status == PASS:
            lines += [f"- **{c.id}** ({c.category}): {c.summary} ({c.elapsed_ms}ms)"]

    md_path.write_text("\n".join(lines) + "\n")
    return json_path, md_path


def isolated_env(tmp: Path, **overrides: str) -> dict[str, str]:
    """A real environment that cannot touch the user's ~/.jsat state.

    JSAT_CONFIG is deliberately left unset so the run exercises whatever the
    user actually has configured — that is the point of a no-mocking test.
    """
    env = {
        **os.environ,
        "JSAT_DATA_DIR": str(tmp / "jsat-data"),
        "JSAT_IMPROVE_DIR": str(tmp / "improve"),
        "JSAT_SESSIONS_DIR": str(tmp / "sessions"),
        "JSAT_RUNTIME_DIR": str(tmp / "runtime"),
    }
    env.update(overrides)
    return env
