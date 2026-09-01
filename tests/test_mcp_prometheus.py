"""Tests for jsat.mcp.prometheus — start_metrics_server() must not report success
on a port-bind failure.

Regression coverage: previously `_run_server()` bound the HTTPServer inside the
daemon thread. Since thread start is asynchronous, `start_metrics_server()` set
`_server_started = True` and returned True before the thread had a chance to
fail, so a port-already-in-use OSError crashed the daemon thread silently while
the caller believed metrics were being served. The fix binds synchronously in
`start_metrics_server()` itself, so a bind failure is returned to the caller
immediately as False.
"""
from __future__ import annotations

import socket

import pytest

from jsat.mcp import prometheus


@pytest.fixture(autouse=True)
def _reset_prometheus_state(monkeypatch):
    """Isolate module-level state between tests."""
    monkeypatch.setattr(prometheus, "_server_started", False)
    monkeypatch.setattr(prometheus, "_prom_available", False)
    yield


@pytest.mark.ci
def test_start_metrics_server_returns_false_when_port_env_unset(monkeypatch):
    monkeypatch.delenv("JSAT_METRICS_PORT", raising=False)
    assert prometheus.start_metrics_server() is False
    assert prometheus._server_started is False


@pytest.mark.ci
def test_start_metrics_server_returns_false_on_invalid_port(monkeypatch):
    monkeypatch.setenv("JSAT_METRICS_PORT", "not-a-port")
    assert prometheus.start_metrics_server() is False
    assert prometheus._server_started is False


@pytest.mark.ci
def test_start_metrics_server_returns_false_synchronously_on_bind_conflict(monkeypatch):
    """A port already in use must make start_metrics_server() return False
    immediately (not True followed by a silent background crash).
    """
    # Bypass real prometheus_client registration (not the thing under test here,
    # and re-registering the same metric names across tests in one process would
    # collide in prometheus_client's global CollectorRegistry).
    monkeypatch.setattr(prometheus, "_init_prometheus", lambda: True)

    # Occupy a real port first so the real bind attempt inside start_metrics_server()
    # hits a genuine OSError (EADDRINUSE), exactly like the production failure mode.
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.bind(("", 0))
    blocker.listen(1)
    port = blocker.getsockname()[1]
    try:
        monkeypatch.setenv("JSAT_METRICS_PORT", str(port))
        result = prometheus.start_metrics_server()

        assert result is False, (
            "start_metrics_server() must return False synchronously on a bind "
            "conflict, not True with a silently-crashing background thread"
        )
        assert prometheus._server_started is False
    finally:
        blocker.close()


@pytest.mark.ci
def test_start_metrics_server_binds_synchronously_and_returns_true(monkeypatch):
    """On a free port, the bind must happen synchronously inside
    start_metrics_server() (not deferred into the daemon thread), and the
    function must return True only once the socket is genuinely listening.
    """
    monkeypatch.setattr(prometheus, "_init_prometheus", lambda: True)

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("", 0))
    free_port = s.getsockname()[1]
    s.close()

    monkeypatch.setenv("JSAT_METRICS_PORT", str(free_port))
    result = prometheus.start_metrics_server()
    assert result is True
    assert prometheus._server_started is True

    # The port must be bound and already accepting connections right away —
    # not merely "a thread was started that might bind it eventually".
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.settimeout(1)
        probe.connect(("127.0.0.1", free_port))
    finally:
        probe.close()
