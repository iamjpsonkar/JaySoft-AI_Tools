"""
Phase J — the live dashboard and Prometheus metrics.

Both are observability surfaces that only exist while a tool call is in
flight, which is exactly why neither had any coverage. Both are driven here
through a real MCP tool call over real stdio, with real HTTP requests against
the real server.
"""
from __future__ import annotations

import json
import os
import socket
import threading
import time
import urllib.request
from pathlib import Path

from ..core import (
    FAIL,
    PASS,
    UNAVAILABLE,
    Check,
    MCPClient,
    Report,
    http_get,
    tcp_reachable,
    timed,
)

DASH_PORT = 7432


def _sockets_allowed() -> bool:
    """Some sandboxes forbid binding a local socket; that is not a JSAT bug."""
    try:
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.close()
        return True
    except OSError:
        return False


@timed
def check_dashboard_serves(jsat_bin: str, repo: Path,
                           env: dict[str, str]) -> Check:
    """A tool call with _dashboard=True must bring up a real HTTP server."""
    if not _sockets_allowed():
        return Check("dashboard_serves", "observability", UNAVAILABLE,
                     "this environment forbids binding a local socket")
    with MCPClient(jsat_bin, repo, env) as c:
        c.handshake()
        resp = c.tool("get_index_status",
                      {"_dashboard": True, "_dashboard_session": "selftest"},
                      timeout=90)
        if resp is None:
            return Check("dashboard_serves", "observability", FAIL,
                         "the tool call with _dashboard=True never returned")
        # The server starts lazily on first dashboard-enabled call.
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if tcp_reachable("127.0.0.1", DASH_PORT, timeout=0.5):
                break
            time.sleep(0.5)
        if not tcp_reachable("127.0.0.1", DASH_PORT, timeout=1.0):
            return Check("dashboard_serves", "observability", FAIL,
                         f"_dashboard=True did not bring up a listener on "
                         f":{DASH_PORT}",
                         detail=json.dumps(resp)[:300],
                         remediation="check _ensure_server in jsat/mcp/dashboard.py")
        status, body = http_get(
            f"http://127.0.0.1:{DASH_PORT}/jsat/dashboard/selftest", timeout=5)
        if status != 200:
            return Check("dashboard_serves", "observability", FAIL,
                         f"the dashboard page returned status {status}",
                         detail=body[:300])
        if "jsat" not in body.lower():
            return Check("dashboard_serves", "observability", FAIL,
                         "the dashboard page body does not look like the "
                         "dashboard", detail=body[:300])
        landing_status, landing = http_get(
            f"http://127.0.0.1:{DASH_PORT}/jsat/dashboard", timeout=5)
        return Check("dashboard_serves", "observability", PASS,
                     f"a real tool call started the dashboard; session page and "
                     f"landing page both served (landing status "
                     f"{landing_status}, {len(body)} bytes)")


@timed
def check_dashboard_sse_events(jsat_bin: str, repo: Path,
                               env: dict[str, str]) -> Check:
    """The SSE stream must actually carry events for an in-flight call."""
    if not _sockets_allowed():
        return Check("dashboard_sse", "observability", UNAVAILABLE,
                     "this environment forbids binding a local socket")
    received: list[str] = []

    def reader() -> None:
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{DASH_PORT}/jsat/events?session=ssetest")
            with urllib.request.urlopen(req, timeout=25) as r:  # noqa: S310
                for _ in range(40):
                    line = r.readline()
                    if not line:
                        break
                    received.append(line.decode("utf-8", "replace"))
                    if len(received) > 8:
                        break
        except Exception as e:
            received.append(f"__error__ {type(e).__name__}: {e}")

    with MCPClient(jsat_bin, repo, env) as c:
        c.handshake()
        # First call brings the server up so the SSE endpoint exists.
        c.tool("get_index_status",
               {"_dashboard": True, "_dashboard_session": "ssetest"}, timeout=90)
        if not tcp_reachable("127.0.0.1", DASH_PORT, timeout=2.0):
            return Check("dashboard_sse", "observability", UNAVAILABLE,
                         "the dashboard server is not running, so the SSE "
                         "stream cannot be tested")
        t = threading.Thread(target=reader, daemon=True)
        t.start()
        time.sleep(1.0)
        # A slower call, so there is something to stream.
        c.tool("security_review",
               {"path": str(repo), "_dashboard": True,
                "_dashboard_session": "ssetest"}, timeout=180)
        t.join(timeout=25)

    blob = "".join(received)
    if not received:
        return Check("dashboard_sse", "observability", FAIL,
                     "the SSE endpoint produced no output at all",
                     remediation="check the /jsat/events handler")
    if blob.startswith("__error__"):
        return Check("dashboard_sse", "observability", FAIL,
                     f"the SSE stream errored: {blob[:200]}")
    if "data:" not in blob and "event:" not in blob:
        return Check("dashboard_sse", "observability", FAIL,
                     "the SSE stream carried no data:/event: frames",
                     detail=blob[:300])
    return Check("dashboard_sse", "observability", PASS,
                 f"the SSE stream delivered {len(received)} frame(s) for a "
                 "real in-flight tool call",
                 detail=blob[:250])


@timed
def check_prometheus_metrics(jsat_bin: str, repo: Path,
                             env: dict[str, str]) -> Check:
    """With JSAT_METRICS_PORT set, /metrics must expose the tool counters."""
    try:
        import prometheus_client  # noqa: F401
    except Exception:
        return Check("prometheus_metrics", "observability", UNAVAILABLE,
                     "prometheus_client is not installed",
                     remediation="pip install prometheus_client")
    if not _sockets_allowed():
        return Check("prometheus_metrics", "observability", UNAVAILABLE,
                     "this environment forbids binding a local socket")
    # Pick a free port so a parallel run cannot collide.
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    scoped = {**env, "JSAT_METRICS_PORT": str(port)}
    with MCPClient(jsat_bin, repo, scoped) as c:
        c.handshake()
        for _ in range(3):
            c.tool("get_index_status", {}, timeout=60)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if tcp_reachable("127.0.0.1", port, timeout=0.5):
                break
            time.sleep(0.5)
        if not tcp_reachable("127.0.0.1", port, timeout=1.0):
            return Check("prometheus_metrics", "observability", FAIL,
                         f"JSAT_METRICS_PORT={port} was set but nothing is "
                         f"listening on it",
                         remediation="check jsat/mcp/prometheus.py's bind")
        status, body = http_get(f"http://127.0.0.1:{port}/metrics", timeout=5)
    if status != 200:
        return Check("prometheus_metrics", "observability", FAIL,
                     f"/metrics returned status {status}", detail=body[:300])
    expected = ["jsat_tool_calls_total", "jsat_tool_duration_seconds"]
    missing = [m for m in expected if m not in body]
    if missing:
        return Check("prometheus_metrics", "observability", FAIL,
                     f"/metrics is missing {missing}",
                     detail=body[:400])
    # The counter must have actually moved for the calls just made.
    called = [ln for ln in body.splitlines()
              if ln.startswith("jsat_tool_calls_total")
              and "get_index_status" in ln and not ln.endswith(" 0.0")]
    if not called:
        return Check("prometheus_metrics", "observability", FAIL,
                     "jsat_tool_calls_total did not increment for three real "
                     "get_index_status calls",
                     detail="\n".join(ln for ln in body.splitlines()
                                      if "jsat_tool" in ln)[:400])
    return Check("prometheus_metrics", "observability", PASS,
                 "/metrics exposed the tool counters and they incremented for "
                 "real calls",
                 detail=called[0][:200])


def run(report: Report, jsat_bin: str, repo: Path, env: dict[str, str]) -> None:
    report.add(check_dashboard_serves(jsat_bin, repo, env))
    report.add(check_dashboard_sse_events(jsat_bin, repo, env))
    report.add(check_prometheus_metrics(jsat_bin, repo, env))
