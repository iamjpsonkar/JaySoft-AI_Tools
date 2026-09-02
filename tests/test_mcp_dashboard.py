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

import socket
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
def _reset_dashboard_state(monkeypatch):
    """Isolate module-level session state between tests; never opens a real browser."""
    monkeypatch.setattr(dashboard.webbrowser, "open", lambda url: True)
    dashboard._sessions.clear()
    dashboard._call_index.clear()
    dashboard._recent_sessions.clear()
    dashboard._latest_session_slug = None
    yield
    dashboard._sessions.clear()
    dashboard._call_index.clear()
    dashboard._recent_sessions.clear()
    dashboard._latest_session_slug = None


@pytest.fixture(scope="module", autouse=True)
def _shutdown_real_server():
    """Tear down the one real HTTP server bound during this module's tests."""
    yield
    if dashboard._server is not None:
        dashboard._server.shutdown()
        dashboard._server.server_close()
        dashboard._server = None
        dashboard._server_port = 0


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
def test_serve_html_matches_url_slug_and_404s_on_mismatch():
    port = _free_port()
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

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/jsat/dashboard/ghost-session", timeout=2)
    assert exc_info.value.code == 404
