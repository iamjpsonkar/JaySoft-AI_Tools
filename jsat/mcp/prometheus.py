"""Optional Prometheus metrics for JSAT MCP server.

Activates when prometheus_client is installed AND JSAT_METRICS_PORT is set.
Exposes metrics at http://localhost:{JSAT_METRICS_PORT}/metrics

If prometheus_client is not installed, all public functions in this module
become no-ops so callers never need to guard imports.

Usage (automatic — MCPServer calls start_metrics_server() at __init__):
    export JSAT_METRICS_PORT=9091
    jsat mcp  # metrics appear at http://localhost:9091/metrics

Manual (from any JSAT code):
    from jsat.mcp.prometheus import record_call
    record_call("blast_radius", duration_s=0.042, error=False)
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any

_log = logging.getLogger(__name__)

# ── Module-level state ────────────────────────────────────────────────────────
_prom_available = False
_server_started = False
_lock = threading.Lock()

# prometheus_client objects (populated by _init_prometheus)
_tool_calls_total: Any = None        # Counter{tool, status}
_tool_duration_seconds: Any = None   # Histogram{tool}
_graph_nodes_total: Any = None       # Gauge
_cache_hits_total: Any = None        # Counter{tool}


def _init_prometheus() -> bool:
    """Attempt to import prometheus_client and create metrics. Return True on success."""
    global _prom_available
    global _tool_calls_total, _tool_duration_seconds
    global _graph_nodes_total, _cache_hits_total

    if _prom_available:
        return True

    try:
        from prometheus_client import Counter, Gauge, Histogram  # type: ignore[import]

        _tool_calls_total = Counter(
            "jsat_tool_calls_total",
            "Total number of MCP tool invocations",
            ["tool", "status"],  # status: "ok" | "error"
        )
        _tool_duration_seconds = Histogram(
            "jsat_tool_duration_seconds",
            "Latency of each MCP tool call in seconds",
            ["tool"],
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
        )
        _graph_nodes_total = Gauge(
            "jsat_graph_nodes_total",
            "Total number of nodes currently in the JSAT graph",
        )
        _cache_hits_total = Counter(
            "jsat_cache_hits_total",
            "Number of cache hits per tool (when result was served from cache)",
            ["tool"],
        )

        _prom_available = True
        _log.info("jsat.prometheus: prometheus_client loaded, metrics registered")
        return True

    except ImportError:
        _log.debug(
            "jsat.prometheus: prometheus_client not installed — "
            "metrics export disabled. Install with: pip install prometheus_client"
        )
        return False
    except Exception as exc:
        _log.warning("jsat.prometheus: failed to register metrics: %s", exc)
        return False


# ── HTTP server ───────────────────────────────────────────────────────────────

def _make_metrics_handler():
    """Return an HTTP request handler class that serves /metrics."""
    from http.server import BaseHTTPRequestHandler

    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest  # type: ignore[import]

    class _MetricsHandler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path == "/metrics":
                output = generate_latest()
                self.send_response(200)
                self.send_header("Content-Type", CONTENT_TYPE_LATEST)
                self.send_header("Content-Length", str(len(output)))
                self.end_headers()
                self.wfile.write(output)
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not found. Use /metrics\n")

        def log_message(self, fmt, *args):  # suppress default access logs
            _log.debug("jsat.prometheus.http: " + fmt, *args)

    return _MetricsHandler


def _run_server(port: int) -> None:
    """Blocking HTTP server — runs in a daemon thread."""
    from http.server import HTTPServer
    handler = _make_metrics_handler()
    server = HTTPServer(("", port), handler)
    _log.info(
        "jsat.prometheus: metrics server listening on http://0.0.0.0:%d/metrics", port
    )
    server.serve_forever()


# ── Public API ────────────────────────────────────────────────────────────────

def start_metrics_server() -> bool:
    """
    Start the Prometheus HTTP metrics server if:
      1. prometheus_client is installed, AND
      2. JSAT_METRICS_PORT env var is set to a valid integer port.

    Returns True if the server started, False otherwise.
    Idempotent — safe to call multiple times.
    """
    global _server_started

    with _lock:
        if _server_started:
            return True  # Already running

        port_str = os.environ.get("JSAT_METRICS_PORT", "")
        if not port_str:
            _log.debug(
                "jsat.prometheus: JSAT_METRICS_PORT not set — metrics server disabled"
            )
            return False

        try:
            port = int(port_str)
        except ValueError:
            _log.warning(
                "jsat.prometheus: JSAT_METRICS_PORT='%s' is not a valid port integer",
                port_str,
            )
            return False

        if not _init_prometheus():
            return False

        t = threading.Thread(
            target=_run_server,
            args=(port,),
            daemon=True,
            name="jsat-prometheus-metrics",
        )
        t.start()
        _server_started = True
        _log.info("jsat.prometheus: metrics daemon thread started on port %d", port)
        return True


def record_call(tool_name: str, duration_s: float, error: bool = False) -> None:
    """
    Record a completed MCP tool invocation.

    Args:
        tool_name:  Name of the tool (e.g. "blast_radius").
        duration_s: Wall-clock duration in seconds.
        error:      True if the call raised an exception or returned an error.

    This function is always safe to call — if prometheus_client is not installed
    or metrics were not initialised, it silently returns.
    """
    if not _prom_available:
        return
    try:
        status = "error" if error else "ok"
        _tool_calls_total.labels(tool=tool_name, status=status).inc()  # type: ignore[union-attr]
        _tool_duration_seconds.labels(tool=tool_name).observe(duration_s)  # type: ignore[union-attr]
    except Exception as exc:
        _log.debug("jsat.prometheus.record_call failed: %s", exc)


def record_cache_hit(tool_name: str) -> None:
    """
    Record a cache hit for a tool call.

    Args:
        tool_name: Name of the tool that served from cache.

    No-op if prometheus_client is unavailable.
    """
    if not _prom_available:
        return
    try:
        _cache_hits_total.labels(tool=tool_name).inc()  # type: ignore[union-attr]
    except Exception as exc:
        _log.debug("jsat.prometheus.record_cache_hit failed: %s", exc)


def update_graph_nodes(count: int) -> None:
    """
    Update the gauge that tracks total graph node count.

    Call this after an index build or import completes so the metric
    reflects the current graph size.

    Args:
        count: Current total node count.

    No-op if prometheus_client is unavailable.
    """
    if not _prom_available:
        return
    try:
        _graph_nodes_total.set(count)  # type: ignore[union-attr]
        _log.debug("jsat.prometheus: graph_nodes_total updated to %d", count)
    except Exception as exc:
        _log.debug("jsat.prometheus.update_graph_nodes failed: %s", exc)
