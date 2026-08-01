"""jsat.mcp.dashboard — Single-tab session tree dashboard for JSAT tool calls.

Stdlib-only. One persistent HTTP server (port 7432). Each /jsat command gets its
own session; all tool calls in that session appear as a live tree in ONE browser tab.

URLs:
  http://localhost:7432/jsat/dashboard             — landing page: all active + recent sessions
  http://localhost:7432/jsat/dashboard/<session>   — session tree (e.g. /jsat/dashboard/crack)
  http://localhost:7432/jsat/events                — SSE stream for the active session

Session lifecycle:
  start_dashboard()  — registers a call; opens browser only for first call of session
  push_call_event()  — streams a typed event to the browser (checkpoint / result / error)
  finish_call()      — marks a call node ✓ done in the tree (tab stays open)
  session_done()     — marks the whole session finished; tab stays open, server resets after 10s

The browser tab stays open until session_done() is called. An idle-watcher thread fires
session_done() automatically if no call is running for 30s after last activity.
Completed sessions are recorded in _recent_sessions and shown on the landing page.
"""
from __future__ import annotations

import json
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import structlog

_log = structlog.get_logger(__name__)

# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class _CallNode:
    call_id: str
    name: str
    parent_id: str | None   # None = direct child of session root
    status: str = "running" # "running" | "done" | "error"
    start_ts: float = field(default_factory=time.monotonic)
    end_ts: float | None = None


class _DashboardSession:
    def __init__(self, session_name: str, port: int) -> None:
        self.session_name = session_name
        self.port = port
        self.started_at = time.monotonic()
        self.last_activity = time.monotonic()
        self.calls: dict[str, _CallNode] = {}
        self.events: list[dict] = []    # flat ordered SSE event log
        self._lock = threading.Lock()
        self._done = False              # True after session_done() fires

    @property
    def url(self) -> str:
        safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in self.session_name).strip("-")
        return f"http://localhost:{self.port}/jsat/dashboard/{safe}"

    def register_call(self, call_id: str, name: str, parent_id: str | None) -> None:
        with self._lock:
            self.calls[call_id] = _CallNode(call_id=call_id, name=name, parent_id=parent_id)
            self.last_activity = time.monotonic()
        self._append_event({
            "call_id": call_id,
            "parent_id": parent_id,
            "name": name,
            "type": "call_start",
            "msg": name,
            "ts": time.strftime("%H:%M:%S"),
            "session_elapsed": round(time.monotonic() - self.started_at, 1),
        })

    def push(self, call_id: str, event_type: str, msg: str, **extra: Any) -> None:
        with self._lock:
            self.last_activity = time.monotonic()
        ev: dict[str, Any] = {
            "call_id": call_id,
            "parent_id": self.calls[call_id].parent_id if call_id in self.calls else None,
            "name": self.calls[call_id].name if call_id in self.calls else "",
            "type": event_type,
            "msg": msg,
            "ts": time.strftime("%H:%M:%S"),
            "session_elapsed": round(time.monotonic() - self.started_at, 1),
        }
        ev.update(extra)
        self._append_event(ev)

    def finish(self, call_id: str, elapsed_s: float, status: str = "done") -> None:
        with self._lock:
            if call_id in self.calls:
                self.calls[call_id].status = status
                self.calls[call_id].end_ts = time.monotonic()
            self.last_activity = time.monotonic()
        self._append_event({
            "call_id": call_id,
            "parent_id": self.calls[call_id].parent_id if call_id in self.calls else None,
            "name": self.calls[call_id].name if call_id in self.calls else "",
            "type": "call_done",
            "msg": f"completed in {elapsed_s}s",
            "elapsed_s": elapsed_s,
            "status": status,
            "ts": time.strftime("%H:%M:%S"),
            "session_elapsed": round(time.monotonic() - self.started_at, 1),
        })

    def close(self, elapsed_s: float) -> None:
        with self._lock:
            if self._done:
                return
            self._done = True
        self._append_event({
            "call_id": "__session__",
            "parent_id": None,
            "name": self.session_name,
            "type": "session_done",
            "msg": f"Session completed in {elapsed_s}s",
            "elapsed_s": elapsed_s,
            "ts": time.strftime("%H:%M:%S"),
            "session_elapsed": elapsed_s,
        })
        _log.info("dashboard_session_done", session=self.session_name, elapsed_s=elapsed_s)

    def _append_event(self, ev: dict) -> None:
        with self._lock:
            self.events.append(ev)

    @property
    def is_done(self) -> bool:
        return self._done

    def all_calls_finished(self) -> bool:
        with self._lock:
            return all(c.status != "running" for c in self.calls.values())


# ── Module-level singletons ───────────────────────────────────────────────────

_session: _DashboardSession | None = None
_session_lock = threading.Lock()

_server: HTTPServer | None = None
_server_port: int = 0
_server_lock = threading.Lock()

# Recent sessions (completed) — shown on the /jsat/dashboard landing page.
_recent_sessions: list[dict] = []          # [{name, url, elapsed_s, ts}]
_recent_sessions_lock = threading.Lock()
_MAX_RECENT_SESSIONS = 10

_IDLE_TIMEOUT = 30.0     # seconds of no activity → auto session_done
_SHUTDOWN_DELAY = 10.0   # seconds after session_done before session is cleared


# ── HTML page ─────────────────────────────────────────────────────────────────

def _html_page(session_name: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>JSAT — {session_name}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0d1117;color:#c9d1d9;font-family:'Courier New',Courier,monospace;
     font-size:13px;display:flex;flex-direction:column;height:100vh;overflow:hidden}}
header{{background:#161b22;border-bottom:1px solid #30363d;padding:10px 18px;
        display:flex;align-items:center;gap:14px;flex-shrink:0}}
h1{{font-size:14px;color:#58a6ff;font-weight:bold}}
#timer{{color:#8b949e;font-size:12px}}
#status{{font-size:12px;font-weight:bold}}
#status.running{{color:#3fb950;animation:pulse 1.5s infinite}}
#status.done{{color:#8b949e;animation:none}}
#status.error{{color:#f85149;animation:none}}
@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.4}}}}
#copy-btn{{margin-left:auto;background:#21262d;border:1px solid #30363d;
           color:#c9d1d9;padding:3px 10px;border-radius:4px;cursor:pointer;font-size:11px}}
#copy-btn:hover{{background:#30363d}}
#tree{{flex:1;overflow-y:auto;padding:10px 16px}}

/* Call nodes */
.call-node{{margin:4px 0;border:1px solid #21262d;border-radius:5px;overflow:hidden}}
.call-header{{display:flex;align-items:center;gap:8px;padding:5px 10px;
              background:#161b22;cursor:pointer;user-select:none}}
.call-header:hover{{background:#1c2128}}
.toggle{{color:#444d56;font-size:10px;width:10px;display:inline-block;transition:transform .15s}}
.toggle.collapsed{{transform:rotate(-90deg)}}
.call-name{{color:#79c0ff;font-weight:bold;flex:1}}
.call-status{{font-size:11px;font-weight:bold}}
.call-status.running{{color:#3fb950;animation:pulse 1.5s infinite}}
.call-status.done{{color:#3fb950;animation:none}}
.call-status.error{{color:#f85149;animation:none}}
.call-elapsed{{color:#8b949e;font-size:11px}}
.call-body{{padding:4px 10px 6px 22px;background:#0d1117;border-top:1px solid #21262d}}
.call-body.hidden{{display:none}}

/* Sub-call nodes nested inside a call body */
.call-body .call-node{{margin:4px 0;border-color:#30363d}}
.call-body .call-header{{background:#13191f}}

/* Events inside a call */
.ev{{padding:1px 0;line-height:1.5;white-space:pre-wrap;word-break:break-all;font-size:12px}}
.ev-ts{{color:#444d56;user-select:none}}
.ev.checkpoint{{color:#e3b341}}
.ev.result{{color:#56d364}}
.ev.error{{color:#f85149}}
.ev.over_budget{{color:#f0883e}}
.ev.call_done{{color:#3fb950;font-style:italic}}
.ev.agent_response{{color:#a5d6ff;white-space:pre-wrap;
    border-left:2px solid #2f5e8a;padding-left:6px;margin:2px 0;font-size:11px}}
</style>
</head>
<body>
<header>
  <h1>JSAT — {session_name}</h1>
  <span id="timer">0s</span>
  <span id="status" class="running">● RUNNING</span>
  <button id="copy-btn" onclick="copyAll()">Copy logs</button>
</header>
<div id="tree"></div>
<script>
const tree=document.getElementById('tree'),
      statusEl=document.getElementById('status'),
      timerEl=document.getElementById('timer');
const startMs=Date.now();
let done=false,autoScroll=true;
tree.addEventListener('scroll',()=>{{
  autoScroll=tree.scrollHeight-tree.scrollTop-tree.clientHeight<40;
}});
const iv=setInterval(()=>{{if(!done)timerEl.textContent=Math.round((Date.now()-startMs)/1000)+'s';}},500);
function esc(s){{return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}}

// Event delegation: single click listener on #tree handles all call-header clicks.
tree.addEventListener('click',e=>{{
  const h=e.target.closest('[data-call]');
  if(h)toggleNode(h.getAttribute('data-call'));
}});

function createNode(ev){{
  const parent=ev.parent_id
    ?document.getElementById('cb-'+ev.parent_id)
    :tree;
  if(!parent)return;
  // Build via DOM to avoid inline-onclick quoting issues
  const node=document.createElement('div');
  node.className='call-node';node.id='cn-'+ev.call_id;

  const hdr=document.createElement('div');
  hdr.className='call-header';
  hdr.setAttribute('data-call',ev.call_id);
  hdr.innerHTML=
    '<span class="toggle" id="tg-'+ev.call_id+'">▼</span>'
    +'<span class="call-name">'+esc(ev.name)+'</span>'
    +'<span class="call-status running" id="cs-'+ev.call_id+'">●</span>'
    +'<span class="call-elapsed" id="ce-'+ev.call_id+'"></span>';

  const body=document.createElement('div');
  body.className='call-body';body.id='cb-'+ev.call_id;

  node.appendChild(hdr);node.appendChild(body);
  parent.appendChild(node);
  if(autoScroll)tree.scrollTop=tree.scrollHeight;
}}

function markDone(ev){{
  const cs=document.getElementById('cs-'+ev.call_id);
  if(cs){{cs.className='call-status '+(ev.status||'done');cs.textContent=ev.status==='error'?'✗':'✓';}}
  const ce=document.getElementById('ce-'+ev.call_id);
  if(ce)ce.textContent=ev.elapsed_s+'s';
}}

function appendItem(callId,type,msg,ts){{
  const body=document.getElementById('cb-'+callId);
  if(!body)return;
  const d=document.createElement('div');
  d.className='ev '+type;
  d.innerHTML='<span class="ev-ts">['+esc(ts||'')+'] </span>'+esc(msg);
  body.appendChild(d);
  if(autoScroll)tree.scrollTop=tree.scrollHeight;
}}

function toggleNode(callId){{
  const body=document.getElementById('cb-'+callId);
  const tog=document.getElementById('tg-'+callId);
  if(!body)return;
  const hidden=body.classList.toggle('hidden');
  if(tog)tog.classList.toggle('collapsed',hidden);
}}

function markSessionDone(ev){{
  done=true;clearInterval(iv);
  timerEl.textContent=ev.elapsed_s+'s total';
  statusEl.className='done';statusEl.textContent='✓ DONE';
}}

function copyAll(){{
  const lines=[];
  tree.querySelectorAll('.ev').forEach(e=>lines.push(e.textContent));
  navigator.clipboard.writeText(lines.join('\\n')).then(()=>{{
    const b=document.getElementById('copy-btn');
    b.textContent='Copied!';setTimeout(()=>b.textContent='Copy logs',1500);
  }});
}}

const src=new EventSource('/jsat/events');
src.onmessage=e=>{{
  const ev=JSON.parse(e.data);
  switch(ev.type){{
    case 'call_start':   createNode(ev);break;
    case 'call_done':    markDone(ev);appendItem(ev.call_id,'call_done',ev.msg,ev.ts);break;
    case 'session_done': markSessionDone(ev);src.close();break;
    default: appendItem(ev.call_id,ev.type,ev.msg,ev.ts);
  }}
}};
src.onerror=()=>{{if(!done)statusEl.textContent='⚠ Connection lost';}};
</script>
</body>
</html>"""


def _html_landing_page(port: int) -> str:
    """Landing page at /jsat/dashboard listing active and recent sessions."""
    active_sess = _session

    active_html = ""
    if active_sess is not None and not active_sess.is_done:
        elapsed = round(time.monotonic() - active_sess.started_at, 1)
        active_html = f"""
<div class="section">
  <div class="section-title">● Active Session</div>
  <div class="session-row active">
    <a href="{active_sess.url}">{active_sess.session_name}</a>
    <span class="badge running">● RUNNING {elapsed}s</span>
  </div>
</div>"""

    with _recent_sessions_lock:
        recent = list(reversed(_recent_sessions))

    recent_rows = ""
    for s in recent:
        recent_rows += (
            f'<div class="session-row">'
            f'<a href="{s["url"]}">{s["name"]}</a>'
            f'<span class="badge done">✓ {s["elapsed_s"]}s — {s["ts"]}</span>'
            f'</div>\n'
        )

    recent_html = ""
    if recent_rows:
        recent_html = f"""
<div class="section">
  <div class="section-title">Recent Sessions</div>
  {recent_rows}
</div>"""

    empty_html = ""
    if not active_sess and not recent:
        empty_html = '<div class="empty">No sessions yet. Run <code>/jsat magic dashboard=true &lt;task&gt;</code> to start one.</div>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>JSAT Dashboard</title>
<meta http-equiv="refresh" content="5">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0d1117;color:#c9d1d9;font-family:'Courier New',Courier,monospace;
     font-size:13px;padding:24px}}
h1{{font-size:16px;color:#58a6ff;margin-bottom:4px}}
.subtitle{{color:#8b949e;font-size:12px;margin-bottom:24px}}
.section{{margin-bottom:20px}}
.section-title{{color:#8b949e;font-size:11px;text-transform:uppercase;
               letter-spacing:.08em;margin-bottom:8px;border-bottom:1px solid #21262d;
               padding-bottom:4px}}
.session-row{{display:flex;align-items:center;justify-content:space-between;
              padding:8px 12px;border:1px solid #21262d;border-radius:5px;
              margin-bottom:6px;background:#161b22}}
.session-row a{{color:#79c0ff;text-decoration:none;font-weight:bold}}
.session-row a:hover{{text-decoration:underline}}
.session-row.active{{border-color:#3fb950}}
.badge{{font-size:11px;padding:2px 8px;border-radius:3px}}
.badge.running{{color:#3fb950;animation:pulse 1.5s infinite}}
.badge.done{{color:#8b949e}}
@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.4}}}}
.empty{{color:#8b949e;font-style:italic;margin-top:12px}}
code{{background:#21262d;padding:2px 5px;border-radius:3px;font-size:12px}}
.refresh-note{{color:#444d56;font-size:11px;margin-top:16px}}
</style>
</head>
<body>
<h1>JSAT Dashboard</h1>
<div class="subtitle">http://localhost:{port}/jsat/dashboard — auto-refreshes every 5s</div>
{active_html}
{recent_html}
{empty_html}
<div class="refresh-note">Run <code>/jsat &lt;command&gt; dashboard=true &lt;task&gt;</code> to open a session tab.</div>
</body>
</html>"""


# ── HTTP server ───────────────────────────────────────────────────────────────

class _DashboardHTTPServer(HTTPServer):
    allow_reuse_address = True


class _DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        p = self.path.split("?")[0]
        if p in ("/jsat/dashboard", "/jsat/dashboard/"):
            self._serve_landing()
        elif p.startswith("/jsat/dashboard/"):
            self._serve_html()
        elif p == "/jsat/events":
            self._serve_sse()
        elif p.startswith("/dashboard/session"):
            # backward compat redirect — strip /dashboard/session prefix
            slug = p[len("/dashboard/session"):].lstrip("/")
            dest = f"/jsat/dashboard/{slug}" if slug else "/jsat/dashboard/"
            self.send_response(301)
            self.send_header("Location", dest)
            self.end_headers()
        elif p == "/events":
            # backward compat redirect
            self.send_response(301)
            self.send_header("Location", "/jsat/events")
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def _serve_landing(self) -> None:
        body = _html_landing_page(_server_port or 7432).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_html(self) -> None:
        sess = _session
        name = sess.session_name if sess else "jsat"
        body = _html_page(name).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_sse(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            sent = 0
            while True:
                sess = _session
                if sess is None:
                    time.sleep(0.1)
                    continue
                events = sess.events
                while sent < len(events):
                    ev = events[sent]
                    self.wfile.write(f"data: {json.dumps(ev)}\n\n".encode())
                    self.wfile.flush()
                    sent += 1
                    if ev.get("type") == "session_done":
                        return
                if sess.is_done and sent >= len(events):
                    return
                time.sleep(0.05)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def log_message(self, fmt: str, *args: Any) -> None:  # type: ignore[override]
        pass  # suppress stdout noise


# ── Server lifecycle ──────────────────────────────────────────────────────────

def _ensure_server(port: int) -> bool:
    """Start the HTTP server if not already running. Returns True on success."""
    global _server, _server_port
    with _server_lock:
        if _server is not None:
            return True
        try:
            srv = _DashboardHTTPServer(("127.0.0.1", port), _DashboardHandler)
        except OSError as exc:
            _log.error("dashboard_bind_failed", port=port, error=str(exc))
            return False
        _server = srv
        _server_port = port
        t = threading.Thread(target=srv.serve_forever, daemon=True, name="jsat-dashboard")
        t.start()
        _log.info("dashboard_server_started", port=port)
        return True


def _start_idle_watcher(sess: _DashboardSession) -> None:
    """Background thread: auto-fire session_done() after 30s of idle."""
    def _watch() -> None:
        while True:
            time.sleep(5)
            if sess.is_done:
                return
            all_done = sess.all_calls_finished()
            idle_s = time.monotonic() - sess.last_activity
            if all_done and idle_s > _IDLE_TIMEOUT:
                _log.info("dashboard_idle_timeout", session=sess.session_name, idle_s=round(idle_s, 1))
                elapsed = round(time.monotonic() - sess.started_at, 1)
                sess.close(elapsed)
                _schedule_session_reset()
                return

    threading.Thread(target=_watch, daemon=True, name="jsat-dash-idle").start()


def _schedule_session_reset() -> None:
    """Clear the module-level _session after SHUTDOWN_DELAY so a new /jsat gets a fresh one."""
    def _reset() -> None:
        global _session
        time.sleep(_SHUTDOWN_DELAY)
        with _session_lock:
            _session = None
        _log.debug("dashboard_session_cleared")

    threading.Thread(target=_reset, daemon=True, name="jsat-dash-reset").start()


# ── Public API ────────────────────────────────────────────────────────────────

def start_dashboard(
    session_name: str,
    call_id: str,
    tool_name: str,
    parent_id: str | None,
    port: int = 7432,
) -> tuple[str, bool]:
    """Register a tool call with the dashboard session.

    Args:
        session_name: The /jsat command name (e.g. "magic") — becomes URL slug.
        call_id:      UUID hex[:8] for this specific tool invocation.
        tool_name:    The MCP tool name (e.g. "query", "blast_radius").
        parent_id:    Parent call's call_id, or None for top-level calls.
        port:         HTTP port (default 7432).

    Returns (url, open_browser). open_browser=True only when a new session is created.
    """
    global _session

    if not _ensure_server(port):
        safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in session_name).strip("-")
        return f"http://localhost:{port}/jsat/dashboard/{safe}", False

    with _session_lock:
        sess = _session
        is_new_session = sess is None or sess.is_done

        if is_new_session:
            sess = _DashboardSession(session_name, port)
            _session = sess
            _start_idle_watcher(sess)
            _log.info("dashboard_session_created", session=session_name, url=sess.url)
        else:
            _log.debug("dashboard_session_reuse", session=sess.session_name, call=call_id,
                       tool=tool_name)

    sess.register_call(call_id, tool_name, parent_id)

    if is_new_session:
        try:
            opened = webbrowser.open(sess.url)
            if not opened:
                _log.warning("dashboard_browser_open_failed", url=sess.url)
        except Exception as exc:
            _log.warning("dashboard_browser_open_error", url=sess.url, error=str(exc))

    return sess.url, is_new_session


def push_call_event(call_id: str, event_type: str, msg: str, **extra: Any) -> None:
    """Push a typed event for a call. Thread-safe. No-op if no active session."""
    sess = _session
    if sess is None or sess.is_done:
        return
    try:
        sess.push(call_id, event_type, msg, **extra)
    except Exception as exc:
        _log.warning("dashboard_push_failed", call_id=call_id, error=str(exc))


def finish_call(call_id: str, elapsed_s: float, status: str = "done") -> None:
    """Mark a call done. Tab stays open; idle timer handles session close."""
    sess = _session
    if sess is None:
        return
    try:
        sess.finish(call_id, elapsed_s, status)
        _log.debug("dashboard_call_finished", call_id=call_id, elapsed_s=elapsed_s, status=status)
    except Exception as exc:
        _log.warning("dashboard_finish_failed", call_id=call_id, error=str(exc))


def session_done(elapsed_s: float) -> None:
    """Mark the whole session done (called when /jsat command ends or on single-tool call).
    Tab stays open; session is cleared after SHUTDOWN_DELAY seconds.
    Records the session in _recent_sessions for the landing page.
    """
    sess = _session
    if sess is None:
        return
    sess.close(elapsed_s)
    # Record in history for the landing page
    with _recent_sessions_lock:
        _recent_sessions.append({
            "name": sess.session_name,
            "url": sess.url,
            "elapsed_s": elapsed_s,
            "ts": time.strftime("%H:%M:%S"),
        })
        if len(_recent_sessions) > _MAX_RECENT_SESSIONS:
            _recent_sessions.pop(0)
    _schedule_session_reset()


# ── Backward-compat shim (old callers used push_event / stop_dashboard) ──────

def push_event(type: str, msg: str, **extra: Any) -> None:  # noqa: A002
    """Deprecated shim — routes to push_call_event with a synthetic call_id."""
    sess = _session
    if sess is None:
        return
    # Route to the most recent running call if available, else session root
    with sess._lock:
        running = [c for c in sess.calls.values() if c.status == "running"]
    cid = running[-1].call_id if running else "__session__"
    push_call_event(cid, type, msg, **extra)


def stop_dashboard(elapsed_s: float) -> None:
    """Deprecated shim — calls session_done()."""
    session_done(elapsed_s)
