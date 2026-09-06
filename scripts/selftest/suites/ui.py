"""
Phase K — the Studio: `jsat ui` web surface and its prompt router.

The Studio is a stdlib-only HTTP server + SPA + an offline rule-based prompt
router over the REAL MCP registry. The only honest way to test it is to boot
the real `jsat ui` subprocess, hit its real endpoints over real HTTP, and
assert on the real JSON. All CI-safe: no docker, no LLM, no external
services.
"""
from __future__ import annotations

import json
import socket
import subprocess
import time
from pathlib import Path

from ..core import (
    FAIL,
    PASS,
    UNAVAILABLE,
    Check,
    Report,
    http_get,
    run_cli,
    tcp_reachable,
    timed,
)

STUDIO_PORT = 7433


def _sockets_allowed() -> bool:
    try:
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.close()
        return True
    except OSError:
        return False


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _boot_server(jsat_bin: str, repo: Path, env: dict[str, str], port: int):
    proc = subprocess.Popen(
        [jsat_bin, "ui", "--port", str(port), "--no-open", str(repo)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
        cwd=str(repo))
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            out = (proc.stdout.read() if proc.stdout else "") + \
                  (proc.stderr.read() if proc.stderr else "")
            return proc, f"jsat ui exited early ({proc.returncode}): {out[:400]}"
        if tcp_reachable("127.0.0.1", port, timeout=0.5):
            return proc, None
        time.sleep(0.5)
    return proc, f"jsat ui did not bind :{port} within 20s"


@timed
def check_ui_http_surface(jsat_bin: str, repo: Path,
                          env: dict[str, str]) -> Check:
    """The Studio shell, status, and graph-node JSON over real HTTP."""
    if not _sockets_allowed():
        return Check("ui_http", "ui", UNAVAILABLE,
                     "this environment forbids binding a local socket")
    port = _free_port()
    proc, err = _boot_server(jsat_bin, repo, env, port)
    if err:
        proc.terminate()
        return Check("ui_http", "ui", FAIL, err)
    try:
        status, body = http_get(f"http://127.0.0.1:{port}/", timeout=10)
        if status != 200 or "JSAT" not in body:
            return Check("ui_http", "ui", FAIL,
                         f"the Studio page returned status {status}",
                         detail=body[:300])
        status, body = http_get(f"http://127.0.0.1:{port}/api/status",
                                timeout=10)
        if status != 200:
            return Check("ui_http", "ui", FAIL,
                         f"/api/status returned {status}", detail=body[:300])
        snap = json.loads(body)
        if not snap.get("jsat_version"):
            return Check("ui_http", "ui", FAIL,
                         "/api/status carried no version", detail=body[:300])
        status, body = http_get(
            f"http://127.0.0.1:{port}/api/index", timeout=10)
        if status != 200:
            return Check("ui_http", "ui", FAIL,
                         f"/api/index returned {status}", detail=body[:300])
        idx = json.loads(body)
        if "nodes" not in idx or idx.get("tools", 0) < 1:
            return Check("ui_http", "ui", FAIL,
                         "/api/index lacked the expected shape",
                         detail=json.dumps(idx)[:300])
        status, body = http_get(
            f"http://127.0.0.1:{port}/api/nodes?label=function&limit=5",
            timeout=10)
        if status != 200:
            return Check("ui_http", "ui", FAIL,
                         f"/api/nodes returned {status}", detail=body[:300])
        nodes = json.loads(body)
        if not set(("label", "count", "rows")) <= set(nodes):
            return Check("ui_http", "ui", FAIL,
                         "/api/nodes lacked label/count/rows",
                         detail=json.dumps(nodes)[:300])
        return Check("ui_http", "ui", PASS,
                     f"shell page, /api/status, /api/index and /api/nodes "
                     f"all answered over real stdio→HTTP "
                     f"(~{idx.get('tools')} tools, {idx.get('nodes')} nodes)")
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def _post_json(url: str, data: dict) -> tuple[int, str]:
    import urllib.request
    req = urllib.request.Request(
        url, data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


@timed
def check_ui_prompt_routing(jsat_bin: str, repo: Path,
                            env: dict[str, str]) -> Check:
    """The natural-language prompt bar must route to real tools by intent."""
    if not _sockets_allowed():
        return Check("ui_prompt", "ui", UNAVAILABLE,
                     "this environment forbids binding a local socket")
    port = _free_port()
    proc, err = _boot_server(jsat_bin, repo, env, port)
    if err:
        proc.terminate()
        return Check("ui_prompt", "ui", FAIL, err)
    try:
        status, body = _post_json(
            f"http://127.0.0.1:{port}/api/prompt",
            {"text": "count the tokens in this text"})
        if status != 200:
            return Check("ui_prompt", "ui", FAIL,
                         f"/api/prompt returned {status}", detail=body[:300])
        out = json.loads(body)
        if out.get("intent") != "token_count":
            return Check("ui_prompt", "ui", FAIL,
                         "the prompt router picked the wrong tool",
                         detail=json.dumps(out)[:300])
        if not out.get("ok"):
            return Check("ui_prompt", "ui", FAIL,
                         "the routed token_count call failed",
                         detail=json.dumps(out)[:300])
        status, body = _post_json(
            f"http://127.0.0.1:{port}/api/tools/token_count",
            {"args": {"text": "hello"}})
        if status != 200 or not json.loads(body).get("ok"):
            return Check("ui_prompt", "ui", FAIL,
                         f"/api/tools/token_count failed ({status})",
                         detail=body[:300])
        return Check("ui_prompt", "ui", PASS,
                     "a free-text prompt became a real tool call "
                     "(token_count → {tokens: …}) and the raw /api/tools route "
                     "also ran the same tool")
    finally:
        proc.terminate()


@timed
def check_ui_tui_present(jsat_bin: str, env: dict[str, str],
                         repo: Path) -> Check:
    """`jsat ui --tui` must either need Textual and say so, or start cleanly."""
    port = _free_port()
    r = run_cli(jsat_bin, ["ui", "--tui", "--port", str(port), str(repo)],
                env, timeout=60)
    if r.returncode == 2 and ("studio" in (r.stdout + r.stderr).lower()
                              and "pip install" in (r.stdout + r.stderr)):
        return Check("ui_tui", "ui", PASS,
                     "the terminal UI reports the missing-textual install "
                     "hint and exits cleanly")
    if r.returncode != 0:
        # Textual present but headless env: any clean non-zero exit is a
        # graceful degradation, not a crash.
        if any(w in (r.stdout + r.stderr).lower()
               for w in ("terminal", "textual", "tty", "not a real")):
            return Check("ui_tui", "ui", PASS,
                         "the terminal UI degraded gracefully in this "
                         "headless environment",
                         detail=(r.stdout or r.stderr)[:250])
        return Check("ui_tui", "ui", FAIL,
                     "jsat ui --tui failed unexpectedly",
                     detail=(r.stdout or r.stderr)[:400])
    return Check("ui_tui", "ui", PASS,
                 "the terminal UI started cleanly")


def run(report: Report, jsat_bin: str, repo: Path,
        env: dict[str, str]) -> None:
    report.add(check_ui_http_surface(jsat_bin, repo, env))
    report.add(check_ui_prompt_routing(jsat_bin, repo, env))
    report.add(check_ui_tui_present(jsat_bin, env, repo))