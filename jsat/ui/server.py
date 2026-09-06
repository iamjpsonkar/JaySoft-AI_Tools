"""jsat.ui.server — zero-dependency HTTP server for the Studio web app.

A stdlib ``ThreadingHTTPServer`` bound to 127.0.0.1 exposes the Studio API and
serves the single-page app. There is no framework and no HTML dependency:
the app bundle lives in ``jsat/ui/_app.py`` as static strings, like the
dashboard. ``jsat ui`` (see ``jsat._cli_ui``) is the entry point.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import webbrowser
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from jsat.ui._api import StudioAPI

_log = logging.getLogger(__name__)

_PORT_DEFAULT = 7433
_BASE = "/studio"


class _StudioHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # ── wiring ─────────────────────────────────────────────────────────────
    @property
    def api(self) -> StudioAPI:
        server: StudioServer = self.server  # type: ignore[assignment]
        return server.api

    # ── routing ────────────────────────────────────────────────────────────
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        q = parse_qs(parsed.query)

        if path == "/" or path == _BASE:
            self._serve_page()
        elif path == "/app.js":
            self._serve_static(_APP_JS, "text/javascript")
        elif path == "/app.css":
            self._serve_static(_APP_CSS, "text/css")
        elif path == "/api/status":
            self._json(self.api.status())
        elif path == "/api/index":
            self._json(self.api.index())
        elif path == "/api/tools":
            self._json({"tools": self.api.catalog()})
        elif path == "/api/nodes":
            self._json(self.api.nodes(q.get("label", ["function"])[0],
                                      _int(q.get("limit", ["300"])[0], 300)))
        elif path == "/api/sessions":
            self._json({"sessions": self.api.sessions()})
        elif path == "/api/plans":
            self._json({"plans": self.api.plans()})
        elif path == "/api":
            self._json({"endpoints": ["status", "index", "tools", "tools/<name>",
                                      "prompt", "nodes?label=", "sessions", "plans"],
                        "dashboard_url": "http://127.0.0.1:7432/jsat/dashboard"})
        else:
            self._json({"error": "not found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._json({"error": "invalid JSON body"}, status=400)
            return
        if path == "/api/prompt":
            self._json(self.api.prompt(str(body.get("text", ""))))
        elif path.startswith("/api/tools/"):
            name = path[len("/api/tools/"):].strip("/")
            self._json(self.api.run_tool(name, dict(body.get("args", {}) or {})))
        else:
            self._json({"error": "not found"}, status=404)

    # ── response helpers ───────────────────────────────────────────────────
    def _send(self, data: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control",
                         "no-store" if content_type.startswith("application/json")
                         else "public, max-age=60")
        self.end_headers()
        with suppress(BrokenPipeError, ConnectionResetError):
            self.wfile.write(data)

    def _json(self, obj: object, status: int = 200) -> None:
        self._send(json.dumps(obj, default=str).encode("utf-8"),
                   "application/json; charset=utf-8", status)

    def _serve_static(self, text: str, content_type: str) -> None:
        self._send(text.encode("utf-8"), content_type)

    def _serve_page(self) -> None:
        import jsat.ui._app as app
        self._send(app.PAGE_HTML.encode("utf-8"), "text/html; charset=utf-8")

    def log_message(self, fmt: str, *args: object) -> None:
        _log.debug("studio_request", request=fmt % args)


class StudioServer(ThreadingHTTPServer):
    """Threaded HTTP server hosting the Studio API + single-page app."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, host: str, port: int, api: StudioAPI) -> None:
        super().__init__((host, port), _StudioHandler)
        self.api = api
        self.started_at = time.monotonic()


# module singleton, mirroring the dashboard's
_server: StudioServer | None = None
_lock = threading.Lock()


def _ensure_server(js, port: int, host: str = "127.0.0.1") -> StudioServer | None:
    global _server
    with _lock:
        if _server is not None:
            return _server
        try:
            _server = StudioServer(host, port, StudioAPI(js))
        except OSError as exc:
            _log.error("studio_bind_failed", port=port, error=str(exc))
            return None
        threading.Thread(target=_server.serve_forever, daemon=True,
                         name="jsat-studio").start()
        _log.info("studio_server_started", host=host, port=port)
        return _server


def start_studio(js, port: int = _PORT_DEFAULT, host: str = "127.0.0.1",
                 open_browser: bool = True) -> tuple[str | None, bool]:
    """Start (or reuse) the Studio server. Returns (url, is_new)."""
    srv = _ensure_server(js, port, host)
    if srv is None:
        return None, False
    url = f"http://{host}:{port}"
    if open_browser:
        with suppress(Exception):  # noqa: BLE001
            webbrowser.open(url)
    return url, srv is _server


def stop_studio() -> None:
    global _server
    with _lock:
        if _server is not None:
            _server.shutdown()
            _server.server_close()
            _server = None


def _int(value: str, default: int) -> int:
    try:
        return max(1, int(value))
    except ValueError:
        return default


from jsat.ui._app import APP_CSS, APP_JS  # noqa: E402

_APP_CSS = APP_CSS
_APP_JS = APP_JS

__all__ = ["StudioServer", "start_studio", "stop_studio"]