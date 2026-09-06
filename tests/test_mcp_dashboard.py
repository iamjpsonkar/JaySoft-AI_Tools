"""Tests for jsat.mcp.dashboard — concurrent session isolation.

Regression coverage for the bug where start_dashboard() decided whether to reuse
the existing session based only on `is_done`, ignoring `session_name` entirely —
so two concurrently active /jsat commands with different `_dashboard_session`
names got silently merged into one tab. Also covers the do_GET/_serve_html fix:
the HTTP handler must match the requested URL's session-name slug against the
actual session being served, 404ing on mismatch instead of serving the wrong
session's content.
"""
from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest

from jsat.mcp import dashboard


def _free_port() -> int:
    try:
        s = socket.socket()
    except PermissionError:
        pytest.skip("local socket creation is blocked by this sandbox")
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(autouse=True)
def _reset_dashboard_state(monkeypatch, tmp_path):
    """Isolate module-level session state between tests; never opens a real browser."""
    monkeypatch.setattr(dashboard.webbrowser, "open", lambda url: True)
    monkeypatch.setattr(dashboard, "_archive_dir", lambda: tmp_path / "dashboard")
    dashboard._sessions.clear()
    dashboard._call_index.clear()
    dashboard._recent_sessions.clear()
    dashboard._latest_session_slug = None
    dashboard._archive_cache = (0.0, [])
    yield
    dashboard._sessions.clear()
    dashboard._call_index.clear()
    dashboard._recent_sessions.clear()
    dashboard._latest_session_slug = None
    dashboard._archive_cache = (0.0, [])


@pytest.fixture(scope="module", autouse=True)
def _shutdown_real_server():
    """Tear down the one real HTTP server bound during this module's tests."""
    yield
    if dashboard._server is not None:
        dashboard._server.shutdown()
        dashboard._server.server_close()
        dashboard._server = None
        dashboard._server_port = 0


@pytest.fixture(scope="module")
def _real_port():
    """The module-wide dashboard server binds exactly one port (singleton)."""
    return _free_port()


# ── start_dashboard(): session-name-aware reuse ──────────────────────────────

@pytest.mark.ci
def test_start_dashboard_keeps_concurrent_sessions_with_different_names_separate(monkeypatch):
    monkeypatch.setattr(dashboard, "_ensure_server", lambda port: True)

    url_a, new_a = dashboard.start_dashboard("alpha", "call-a1", "toolA", None, port=7999)
    assert new_a is True
    url_b, new_b = dashboard.start_dashboard("beta", "call-b1", "toolB", None, port=7999)
    assert new_b is True

    # Different names must NOT be merged into the same session/tab.
    assert url_a != url_b
    assert set(dashboard._sessions.keys()) == {"alpha", "beta"}
    assert dashboard._sessions["alpha"].session_name == "alpha"
    assert dashboard._sessions["beta"].session_name == "beta"


@pytest.mark.ci
def test_start_dashboard_reuses_same_name_while_active(monkeypatch):
    monkeypatch.setattr(dashboard, "_ensure_server", lambda port: True)

    url_a1, new_a1 = dashboard.start_dashboard("alpha", "call-a1", "toolA", None, port=7999)
    assert new_a1 is True
    url_a2, new_a2 = dashboard.start_dashboard("alpha", "call-a2", "toolA2", None, port=7999)

    # Same name, still active (not done) -> reuse, not a new session.
    assert new_a2 is False
    assert url_a2 == url_a1
    assert len(dashboard._sessions) == 1


@pytest.mark.ci
def test_call_events_route_to_the_correct_session(monkeypatch):
    monkeypatch.setattr(dashboard, "_ensure_server", lambda port: True)
    dashboard.start_dashboard("alpha", "call-a1", "toolA", None, port=7999)
    dashboard.start_dashboard("beta", "call-b1", "toolB", None, port=7999)

    dashboard.push_call_event("call-a1", "checkpoint", "doing alpha work")
    dashboard.push_call_event("call-b1", "checkpoint", "doing beta work")

    alpha_msgs = [e["msg"] for e in dashboard._sessions["alpha"].events]
    beta_msgs = [e["msg"] for e in dashboard._sessions["beta"].events]
    assert "doing alpha work" in alpha_msgs
    assert "doing beta work" in beta_msgs
    # The bug would let one session's events bleed into the other's tree.
    assert "doing alpha work" not in beta_msgs
    assert "doing beta work" not in alpha_msgs


# ── do_GET / _serve_html: slug must match the actual session being served ───

@pytest.mark.ci
def test_serve_html_matches_url_slug_and_404s_on_mismatch(_real_port):
    port = _real_port
    dashboard.start_dashboard("alpha", "call-a1", "toolA", None, port=port)
    dashboard.start_dashboard("beta", "call-b1", "toolB", None, port=port)
    time.sleep(0.05)  # give the daemon thread a moment to be ready

    resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/jsat/dashboard/alpha", timeout=2)
    assert resp.status == 200
    body_alpha = resp.read().decode()
    assert "alpha" in body_alpha

    resp2 = urllib.request.urlopen(f"http://127.0.0.1:{port}/jsat/dashboard/beta", timeout=2)
    assert resp2.status == 200
    body_beta = resp2.read().decode()
    assert "beta" in body_beta
    # Must not silently serve the other session's content for this slug.
    assert "JSAT — alpha" not in body_beta

    # Unknown sessions still get the app shell (client resolves via /data)…
    resp3 = urllib.request.urlopen(
        f"http://127.0.0.1:{port}/jsat/dashboard/ghost-session", timeout=2)
    assert resp3.status == 200
    # …but the data endpoint 404s instead of serving junk or a wrong session.
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(
            f"http://127.0.0.1:{port}/jsat/dashboard/ghost-session/data", timeout=2)
    assert exc_info.value.code == 404


# ── call metadata: budget/mode/args, truncation, wall-clock + seq ────────────

@pytest.mark.ci
def test_call_records_budget_mode_args_and_truncates_huge_args(monkeypatch):
    monkeypatch.setattr(dashboard, "_ensure_server", lambda port: True)
    dashboard.start_dashboard("big", "call-big", "jsat__query", None, port=7999,
                              budget_s=3.0, mode="beast", args="x" * 20_000)

    call = dashboard._sessions["big"].calls["call-big"]
    assert call.budget_s == 3.0
    assert call.mode == "beast"
    assert call.name == "jsat__query"
    assert len(call.args) < 9000
    assert "truncated" in call.args


@pytest.mark.ci
def test_events_carry_seq_and_wall_ms_and_payload_is_truncated(monkeypatch):
    monkeypatch.setattr(dashboard, "_ensure_server", lambda port: True)
    dashboard.start_dashboard("seq", "call-1", "toolA", None, port=7999)
    dashboard.push_call_event("call-1", "checkpoint", "step one")
    dashboard.push_call_event("call-1", "result", "ok", payload="y" * 70_000)

    events = dashboard._sessions["seq"].events
    assert [e["seq"] for e in events] == [1, 2, 3]
    assert all(e["wall_ms"] > 0 for e in events)
    assert all("wall_ms" in e for e in events)
    result = [e for e in events if e["type"] == "result"][0]
    assert len(result["payload"]) <= dashboard._MAX_PAYLOAD + 60
    assert "chars omitted]" in result["payload"]


# ── real HTTP endpoints: /data snapshot, scoped SSE, archive, stats, summary ─

@pytest.mark.ci
def test_data_endpoint_returns_snapshot_scoped_to_slug(_real_port):
    port = _real_port
    dashboard.start_dashboard("alpha", "call-a1", "toolA", None, port=port)
    dashboard.push_call_event("call-a1", "checkpoint", "alpha progress")
    dashboard.start_dashboard("beta", "call-b1", "toolB", None, port=port)
    dashboard.push_call_event("call-b1", "checkpoint", "beta progress")
    time.sleep(0.05)

    alpha = json.loads(urllib.request.urlopen(
        f"http://127.0.0.1:{port}/jsat/dashboard/alpha/data", timeout=2).read())
    assert alpha["session"]["session_name"] == "alpha"
    assert "call-a1" in alpha["calls"]
    assert "call-b1" not in alpha["calls"]
    assert any(e["msg"] == "alpha progress" for e in alpha["events"])
    assert not any(e["msg"] == "beta progress" for e in alpha["events"])

    beta = json.loads(urllib.request.urlopen(
        f"http://127.0.0.1:{port}/jsat/dashboard/beta/data", timeout=2).read())
    assert beta["session"]["session_name"] == "beta"
    assert "call-b1" in beta["calls"]


@pytest.mark.ci
def test_sse_streams_only_the_requested_sessions_events(_real_port):
    port = _real_port
    dashboard.start_dashboard("alpha", "call-a1", "toolA", None, port=port)
    dashboard.start_dashboard("beta", "call-b1", "toolB", None, port=port)

    frames: list[bytes] = []
    def _reader():
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/jsat/dashboard/alpha/events", timeout=15) as resp:
            while len(frames) < 8:
                line = resp.readline()
                if not line:
                    break
                frames.append(line)

    thread = threading.Thread(target=_reader)
    thread.start()
    time.sleep(0.2)
    dashboard.push_call_event("call-a1", "checkpoint", "alpha progress")
    dashboard.push_call_event("call-b1", "checkpoint", "beta progress")
    dashboard.session_done(0.1, call_id="call-a1")
    thread.join(timeout=10)

    blob = b"".join(frames).decode()
    assert "alpha progress" in blob
    assert "beta progress" not in blob


@pytest.mark.ci
def test_session_archives_to_disk_and_stats_and_summary_endpoints(_real_port, monkeypatch):
    dashboard._ensure_server(port := _real_port)
    dashboard.start_dashboard("arch", "call-a1", "jsat__get_function", None, port=port)
    dashboard.push_call_event("call-a1", "checkpoint", "worked")
    dashboard.finish_call("call-a1", 0.2, status="done")
    dashboard.session_done(0.2)
    time.sleep(0.3)  # archive write is async

    entries = dashboard._archive_list()
    assert entries, "archive should contain the finished session"
    name = entries[-1]["file"]

    doc = json.loads(urllib.request.urlopen(
        f"http://127.0.0.1:{port}/jsat/dashboard/archive/{name}", timeout=2).read())
    assert doc["session"]["session_name"] == "arch"
    assert doc["calls"]["call-a1"]["status"] == "done"
    assert doc["stats"]["jsat__get_function"]["calls"] == 1

    archive = json.loads(urllib.request.urlopen(
        f"http://127.0.0.1:{port}/jsat/dashboard/archive", timeout=2).read())
    assert any(e["file"] == name for e in archive)

    stats = json.loads(urllib.request.urlopen(
        f"http://127.0.0.1:{port}/jsat/dashboard/stats", timeout=2).read())
    assert stats["totals"]["calls"] >= 1
    assert any(r["tool"] == "jsat__get_function" and r["calls"] >= 1
               for r in stats["per_tool"])

    summary = json.loads(urllib.request.urlopen(
        f"http://127.0.0.1:{port}/jsat/dashboard/summary", timeout=2).read())
    recent = [r for r in summary["recent"] if r["name"] == "arch"]
    assert recent and recent[0]["archive"]
    assert all(r["name"] != "arch" for r in summary["active"])


@pytest.mark.ci
def test_replay_and_compare_pages_serve_with_mode(_real_port):
    port = _real_port
    dashboard._ensure_server(port)
    dashboard.start_dashboard("alpha", "call-a1", "toolA", None, port=port,
                              budget_s=4.0, mode="plan")
    dashboard.session_done(0.1)
    time.sleep(0.3)
    name = dashboard._archive_list()[-1]["file"]

    replay = urllib.request.urlopen(
        f"http://127.0.0.1:{port}/jsat/dashboard/replay?file={name}", timeout=2).read().decode()
    assert '"mode": "replay"' in replay

    second = urllib.request.urlopen(
        f"http://127.0.0.1:{port}/jsat/dashboard/compare?a={name}&b={name}",
        timeout=2).read().decode()
    assert '"mode": "compare"' in second
