"""jsat.mcp.dashboard — the JSAT observability dashboard.

Stdlib-only. One persistent ``ThreadingHTTPServer`` (port 7432, override with
``JSAT_DASHBOARD_PORT``). Every ``/jsat`` command gets its own session; all tool
calls in that session appear live in ONE browser tab as a session you can watch
in three ways — a **waterfall timeline** (every call is a bar on a shared time
axis with its budget drawn in), the classic **tree**, and a **stats** view
(per-tool latency p95/max, error & over-budget counts). Clicking any call opens
a drawer with the call's actual args and result payload.

URLs:
  http://localhost:7432/jsat/dashboard                    landing (active + archived)
  http://localhost:7432/jsat/dashboard/<session>          live session tab
  http://localhost:7432/jsat/dashboard/<session>/events   SSE stream for ONE session
  http://localhost:7432/jsat/dashboard/<session>/data     JSON snapshot of a session
  http://localhost:7432/jsat/dashboard/stats              aggregate analytics (JSON)
  http://localhost:7432/jsat/dashboard/summary            lightweight landing JSON
  http://localhost:7432/jsat/dashboard/archive            archived sessions (JSON)
  http://localhost:7432/jsat/dashboard/archive/<file>     one archived session (JSON)
  http://localhost:7432/jsat/dashboard/replay?file=<f>    scrub through a finished run
  http://localhost:7432/jsat/dashboard/compare?a=<f>&b=<f>  align two runs side by side
  http://localhost:7432/jsat/events                       [deprecated] latest session SSE

Session lifecycle:
  start_dashboard()  — registers a call; opens browser only for first call of session
  push_call_event()  — streams a typed event to the browser (checkpoint / result / error)
  finish_call()      — marks a call node ✓ done; captures elapsed, payload
  session_done()     — marks the whole session finished, archives it to disk, tab stays open

Completed sessions are archived as JSON under JSAT_DATA_DIR/dashboard (or
~/.jsat/dashboard) and listed on the landing page for replay and comparison.
An idle-watcher thread fires session_done() automatically after 30s of quiet.

Public API is backward-compatible: push_event() / stop_dashboard() shims remain.
"""
from __future__ import annotations

import json
import os
import threading
import time
import webbrowser
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import structlog

from jsat.mcp._dashboard_app import APP_JS

_log = structlog.get_logger(__name__)

_PORT_DEFAULT = 7432

_IDLE_TIMEOUT = 30.0      # seconds of no activity → auto session_done
_SHUTDOWN_DELAY = 10.0    # seconds after session_done before the session is cleared
_MAX_RECENT_SESSIONS = 10  # landing history ring
_MAX_EVENTS = 3000         # events kept per session (oldest dropped)
_MAX_ARCHIVES = 50         # archived session files retained on disk
_MAX_ARGS = 8000           # chars of serialized args stored per call
_MAX_PAYLOAD = 60_000      # chars of result/error payload stored per call


def _slugify(session_name: str) -> str:
    """Turn a session name into the URL-safe slug used to key sessions and routes."""
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in session_name).strip("-")


def _now_wall_ms() -> int:
    """Wall-clock epoch milliseconds — the axis the waterfall renders on."""
    return int(time.time() * 1000)


def _truncate(text: str, limit: int) -> str:
    """Truncate a string at a char budget, marking cuts so the UI can tell."""
    if text is None or len(text) <= limit:
        return text
    return text[:limit] + f"\n… [truncated, {len(text) - limit} chars omitted]"


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class _CallNode:
    call_id: str
    name: str
    parent_id: str | None   # None = direct child of the session root
    depth: int = 0
    status: str = "running"  # "running" | "done" | "error"
    start_mono: float = field(default_factory=time.monotonic)
    end_mono: float | None = None
    start_wall_ms: int = field(default_factory=_now_wall_ms)
    end_wall_ms: int | None = None
    budget_s: float | None = None
    mode: str = "default"   # "default" | "plan" | "beast"
    args: str | None = None   # truncated JSON string of the tool's args
    payload: str | None = None  # truncated result/error text
    error: str | None = None
    elapsed_s: float | None = None

    def to_dict(self) -> dict:
        e = self.elapsed_s
        if e is None and self.end_wall_ms and self.start_wall_ms:
            e = round((self.end_wall_ms - self.start_wall_ms) / 1000, 2)
        return {
            "call_id": self.call_id,
            "name": self.name,
            "parent_id": self.parent_id,
            "depth": self.depth,
            "status": self.status,
            "start_wall_ms": self.start_wall_ms,
            "end_wall_ms": self.end_wall_ms,
            "budget_s": self.budget_s,
            "mode": self.mode,
            "args": self.args,
            "payload": self.payload,
            "error": self.error,
            "elapsed_s": e,
        }


class _DashboardSession:
    def __init__(self, session_name: str, port: int) -> None:
        self.session_name = session_name
        self.slug = _slugify(session_name) or "session"
        self.port = port
        self.started_at = time.monotonic()
        self.last_activity = time.monotonic()
        self.started_wall_ms = _now_wall_ms()
        self.ended_wall_ms: int | None = None
        self.calls: dict[str, _CallNode] = {}
        self.events: list[dict] = []
        self.seq = 0
        self._lock = threading.Lock()
        self._done = False

    @property
    def url(self) -> str:
        return f"http://localhost:{self.port}/jsat/dashboard/{self.slug}"

    def register_call(self, call_id: str, name: str, parent_id: str | None, *,
                      budget_s: float | None = None, mode: str = "default",
                      args: str | None = None) -> None:
        depth = 0
        if parent_id:
            with self._lock:
                parent = self.calls.get(parent_id)
                if parent:
                    depth = parent.depth + 1
        with self._lock:
            self.calls[call_id] = _CallNode(
                call_id=call_id, name=name, parent_id=parent_id, depth=depth,
                budget_s=budget_s, mode=mode, args=_truncate(args, _MAX_ARGS),
            )
            self.last_activity = time.monotonic()
        self._append_event({
            "type": "call_start",
            "call_id": call_id,
            "parent_id": parent_id,
            "name": name,
            "depth": depth,
            "msg": name,
            "budget_s": budget_s,
            "mode": mode,
            "args": _truncate(args, _MAX_ARGS),
            "ts": time.strftime("%H:%M:%S"),
            "session_elapsed": round(time.monotonic() - self.started_at, 1),
        })

    def push(self, call_id: str, event_type: str, msg: str, **extra: Any) -> None:
        c: _CallNode | None = None
        with self._lock:
            self.last_activity = time.monotonic()
            c = self.calls.get(call_id)
            payload = extra.get("payload")
            if payload is not None:
                extra["payload"] = _truncate(str(payload), _MAX_PAYLOAD)
                if c is not None:
                    c.payload = extra["payload"]
            if event_type == "error" and c is not None and not c.error:
                c.error = _truncate(str(msg), _MAX_PAYLOAD)
        ev: dict[str, Any] = {
            "type": event_type,
            "call_id": call_id,
            "parent_id": c.parent_id if c else extra.get("parent_id"),
            "name": c.name if c else extra.get("name", ""),
            "msg": msg,
            "ts": time.strftime("%H:%M:%S"),
            "session_elapsed": round(time.monotonic() - self.started_at, 1),
        }
        ev.update(extra)
        self._append_event(ev)

    def finish(self, call_id: str, elapsed_s: float, status: str = "done") -> None:
        c: _CallNode | None = None
        with self._lock:
            c = self.calls.get(call_id)
            if c is not None:
                c.status = status
                c.end_mono = time.monotonic()
                c.end_wall_ms = _now_wall_ms()
                c.elapsed_s = elapsed_s
            self.last_activity = time.monotonic()
        cid = c.call_id if c else call_id
        pid = c.parent_id if c else None
        name = c.name if c else ""
        self._append_event({
            "type": "call_done",
            "call_id": cid,
            "parent_id": pid,
            "name": name,
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
            self.ended_wall_ms = self.started_wall_ms + int(elapsed_s * 1000)
        self._append_event({
            "type": "session_done",
            "call_id": "__session__",
            "parent_id": None,
            "name": self.session_name,
            "msg": f"Session completed in {elapsed_s}s",
            "elapsed_s": elapsed_s,
            "ts": time.strftime("%H:%M:%S"),
            "session_elapsed": elapsed_s,
        })
        _log.info("dashboard_session_done", session=self.session_name, slug=self.slug,
                  elapsed_s=elapsed_s)

    def _append_event(self, ev: dict) -> None:
        with self._lock:
            self.seq += 1
            ev["seq"] = self.seq
            ev["wall_ms"] = _now_wall_ms()
            self.events.append(ev)
            if len(self.events) > _MAX_EVENTS:
                self.events = self.events[-_MAX_EVENTS:]

    @property
    def is_done(self) -> bool:
        return self._done

    def all_calls_finished(self) -> bool:
        with self._lock:
            return all(c.status != "running" for c in self.calls.values())

    def events_snapshot(self) -> list[dict]:
        with self._lock:
            return list(self.events)

    def snapshot(self) -> dict:
        """Authoritative JSON document for /data, archives, replay and compare."""
        with self._lock:
            calls = {cid: c.to_dict() for cid, c in self.calls.items()}
            events = list(self.events)
            status = "done" if self._done else "running"
            elapsed = round(self.started_wall_ms and
                            ((self.ended_wall_ms or _now_wall_ms()) - self.started_wall_ms) / 1000, 1)
        return {
            "session": {
                "session_name": self.session_name,
                "slug": self.slug,
                "started_wall_ms": self.started_wall_ms,
                "ended_wall_ms": self.ended_wall_ms,
                "status": status,
                "elapsed_s": elapsed,
            },
            "calls": calls,
            "events": events,
        }

    def tool_stats(self) -> tuple[dict[str, dict], dict]:
        """Per-tool latency/quality aggregates for this session, plus totals."""
        per_tool: dict[str, dict] = {}
        totals = {"calls": 0, "errors": 0, "over_budget": 0, "total_ms": 0}
        with self._lock:
            nodes = list(self.calls.values())
        for c in nodes:
            e = c.elapsed_s
            if e is None and c.end_wall_ms and c.start_wall_ms:
                e = (c.end_wall_ms - c.start_wall_ms) / 1000
            t = per_tool.setdefault(c.name, {"calls": 0, "total_ms": 0.0, "max_ms": 0.0,
                                             "errors": 0, "over_budget": 0})
            t["calls"] += 1
            totals["calls"] += 1
            if c.status == "error":
                t["errors"] += 1
                totals["errors"] += 1
            if e is not None:
                ms = e * 1000
                t["total_ms"] += ms
                if ms > t["max_ms"]:
                    t["max_ms"] = ms
                totals["total_ms"] += ms
            if c.budget_s and e is not None and ms > c.budget_s * 1000 + 50:
                t["over_budget"] += 1
                totals["over_budget"] += 1
        return per_tool, totals


# ── Module-level singletons ───────────────────────────────────────────────────

# Sessions keyed by URL slug so concurrent /jsat commands with different
# `_dashboard_session` names stay in separate tabs. `_latest_session_slug`
# tracks the most recently active session for callers without a call_id and for
# the deprecated global /jsat/events stream.
_sessions: dict[str, _DashboardSession] = {}
_latest_session_slug: str | None = None
_session_lock = threading.Lock()

# call_id -> session slug, routes push_call_event/finish_call/session_done.
_call_index: dict[str, str] = {}

_server: ThreadingHTTPServer | None = None
_server_port: int = 0
_server_lock = threading.Lock()

_recent_sessions: list[dict] = []
_recent_sessions_lock = threading.Lock()

_archive_lock = threading.Lock()
_archive_cache: tuple[float, list[dict]] = (0.0, [])


def _archive_dir() -> Path:
    """Where archived sessions live: $JSAT_DATA_DIR/dashboard or ~/.jsat/dashboard."""
    env = os.environ.get("JSAT_DATA_DIR", "").strip()
    base = Path(env).expanduser().resolve() if env else Path.home() / ".jsat"
    with suppress(OSError):
        base.mkdir(parents=True, exist_ok=True)
    return base / "dashboard"


def _merge_tool_stats(per_tool: list[dict[str, dict]]) -> list[dict]:
    merged: dict[str, dict] = {}
    for pm in per_tool:
        for name, t in pm.items():
            m = merged.setdefault(name, {"calls": 0, "total_ms": 0.0, "max_ms": 0.0,
                                         "errors": 0, "over_budget": 0})
            m["calls"] += t["calls"]
            m["total_ms"] += t["total_ms"]
            m["max_ms"] = max(m["max_ms"], t["max_ms"])
            m["errors"] += t["errors"]
            m["over_budget"] += t["over_budget"]
    rows = []
    for name, m in merged.items():
        rows.append({
            "tool": name,
            "calls": m["calls"],
            "total": round(m["total_ms"], 1),
            "max": round(m["max_ms"], 1),
            "avg": round(m["total_ms"] / m["calls"], 1) if m["calls"] else 0.0,
            "errors": m["errors"],
            "over": m["over_budget"],
        })
    rows.sort(key=lambda r: (r["total"] + r["calls"]), reverse=True)
    return rows


def _archive_list() -> list[dict]:
    """Metadata for every archived session, cached for a couple of seconds."""
    global _archive_cache
    with _archive_lock:
        now = time.monotonic()
        if now - _archive_cache[0] < 2.0 and _archive_cache[1]:
            return list(_archive_cache[1])
        d = _archive_dir()
        out: list[dict] = []
        if d.is_dir():
            for p in sorted(d.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
                try:
                    doc = json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    continue
                sess = doc.get("session", {})
                totals = doc.get("total", {}) or {}
                st = doc.get("stats") or {}
                out.append({
                    "file": p.name,
                    "session_name": sess.get("session_name", p.stem),
                    "slug": sess.get("slug", ""),
                    "started_wall_ms": sess.get("started_wall_ms"),
                    "ended_wall_ms": sess.get("ended_wall_ms"),
                    "elapsed_s": sess.get("elapsed_s"),
                    "status": sess.get("status", "done"),
                    "calls": totals.get("calls") or sum(len(v) for v in st),
                    "errors": totals.get("errors", 0),
                    "over": totals.get("over_budget", 0),
                })
        _archive_cache = (now, out)
        return list(out)


def _write_archive(sess: _DashboardSession) -> None:
    """Persist a finished session to disk (background thread), pruning old files."""
    try:
        snap = sess.snapshot()
        per_tool, totals = sess.tool_stats()
        snap["stats"] = per_tool
        snap["total"] = totals
        d = _archive_dir()
        d.mkdir(parents=True, exist_ok=True)
        name = f"{sess.slug}-{time.strftime('%Y%m%d-%H%M%S')}-{int(time.time())}.json"
        (d / name).write_text(json.dumps(snap, default=str), encoding="utf-8")
        with _archive_lock:
            global _archive_cache
            _archive_cache = (0.0, [])
        _prune_archives(d)
        _log.info("dashboard_archive_written", session=sess.slug, file=name)
    except Exception as exc:
        _log.warning("dashboard_archive_failed", session=sess.slug, error=str(exc))


def _prune_archives(d: Path) -> None:
    try:
        files = sorted(d.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)
        for old in files[_MAX_ARCHIVES:]:
            old.unlink(missing_ok=True)
    except OSError:
        pass


def _stats_document() -> dict:
    """Aggregate analytics across live + archived sessions."""
    per_tool_lists: list[dict[str, dict]] = []
    totals = {"calls": 0, "errors": 0, "over_budget": 0, "total_ms": 0.0}
    session_count = 0

    with _session_lock:
        live = [s for s in _sessions.values()]
    for s in live:
        pt, tt = s.tool_stats()
        per_tool_lists.append(pt)
        for k in totals:
            totals[k] += tt[k]
        session_count += 1

    for arch in _archive_list():
        session_count += 1
        try:
            doc = json.loads((_archive_dir() / arch["file"]).read_text(encoding="utf-8"))
        except Exception:
            continue
        tt = doc.get("total") or {}
        totals["calls"] += tt.get("calls", 0)
        totals["errors"] += tt.get("errors", 0)
        totals["over_budget"] += tt.get("over_budget", 0)
        totals["total_ms"] += tt.get("total_ms", 0.0)
        for name, t in (doc.get("stats") or {}).items():
            per_tool_lists.append({name: t})

    return {
        "updated_ms": _now_wall_ms(),
        "sessions": session_count,
        "totals": {
            "calls": totals["calls"],
            "errors": totals["errors"],
            "over_budget": totals["over_budget"],
            "total_ms": round(totals["total_ms"], 1),
        },
        "per_tool": _merge_tool_stats(per_tool_lists),
    }


# ── HTML page shell (CSS + markup + app) ──────────────────────────────────────
#
# The app script is fully static (jsat/mcp/_dashboard_app.py); the only thing
# the server injects is `window.DASH`, a small JSON dict.
_PAGE_SHELL = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>JSAT Dashboard</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0d1117;color:#c9d1d9;font-family:'Courier New',Courier,monospace;
     font-size:13px;display:flex;flex-direction:column;height:100vh;overflow:hidden}
header{background:#161b22;border-bottom:1px solid #30363d;padding:8px 14px;
       display:flex;align-items:center;gap:10px;flex-wrap:wrap;flex-shrink:0}
h1{font-size:14px;color:#58a6ff;font-weight:bold;margin-right:4px}
.muted{color:#8b949e;font-size:11px}
#timer-el{color:#8b949e;font-size:12px;min-width:70px}
.pill{font-size:11px;font-weight:bold;padding:2px 9px;border-radius:10px;border:1px solid transparent}
.pill.running{color:#3fb950;border-color:#3fb950;animation:pulse 1.5s infinite}
.pill.done{color:#8b949e;border-color:#30363d}
.pill.warn{color:#f0883e;border-color:#f0883e}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
#views{display:flex;gap:4px;margin-left:6px}
.view-btn{background:none;border:1px solid #30363d;color:#8b949e;padding:3px 10px;
          border-radius:4px;cursor:pointer;font-size:11px;font-family:inherit}
.view-btn:hover{color:#c9d1d9}
.view-btn.on{color:#0d1117;background:#58a6ff;border-color:#58a6ff}
#filter-q{background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:4px 8px;
          border-radius:4px;font-size:11px;font-family:inherit;width:170px}
#filter-status{background:#0d1117;border:1px solid #30363d;color:#c9d1d9;
               padding:4px 6px;border-radius:4px;font-size:11px;font-family:inherit}
.icon-btn{background:#21262d;border:1px solid #30363d;color:#c9d1d9;padding:3px 9px;
          border-radius:4px;cursor:pointer;font-size:11px;font-family:inherit}
.icon-btn:hover{background:#30363d}
#spacer{flex:1}
main{flex:1;display:flex;flex-direction:column;min-height:0;position:relative}
.pane{flex:1;display:flex;flex-direction:column;min-height:0}
.hidden{display:none !important}
.wf-toolbar{padding:6px 14px;color:#8b949e;font-size:11px;display:flex;gap:14px;
            border-bottom:1px solid #1c2128}
#wf-ruler{position:relative;height:20px;border-bottom:1px solid #21262d;
          margin-left:14px;margin-right:14px;flex-shrink:0}
.ruler-tick{position:absolute;top:4px;font-size:10px;color:#6e7681;transform:translateX(-4px)}
.ruler-tick:before{content:'';position:absolute;top:14px;left:4px;width:1px;height:6px;background:#30363d}
#wf-area{position:relative;flex:1;overflow:auto;margin:0 6px}
#wf-bars{position:relative;min-height:100%}
.wf-row{position:absolute;left:0;right:0;height:26px;display:flex;cursor:pointer}
.wf-row:hover .wf-label{background:#1c2128}
.wf-label{width:170px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
          color:#79c0ff;font-size:12px;line-height:26px;padding-right:8px}
.wf-row .track{position:absolute;right:8px;height:13px;top:6px}
.bar{position:absolute;height:13px;border-radius:3px;background:#1f6feb;opacity:.9}
.bar.s-running{background:#1f6feb;animation:bpulse 1.5s infinite}
.bar.s-done{background:#2ea043}
.bar.s-error{background:#f85149}
.bar.over{background:#da3633}
.bar.beast .bar-time:after{content:'🐄'}
.bar.plan{background:#8957e5}
.bar .bar-time{position:absolute;right:6px;top:15px;font-size:10px;color:#8b949e;white-space:nowrap}
.budget-mark{position:absolute;top:-3px;bottom:2px;width:1px;background:#f0883e}
@keyframes bpulse{0%,100%{opacity:.75}50%{opacity:1}}
#wf-cursor{position:absolute;top:0;bottom:0;width:1px;background:#f0883e;display:none;z-index:3}
.wf-empty{color:#8b949e;font-style:italic;padding:20px 16px}
.st-ic{display:inline-block;width:16px;color:#8b949e;font-weight:bold}
.st-running{color:#3fb950}
.st-done{color:#3fb950}
.st-error{color:#f85149}
.trow{padding:3px 8px;cursor:pointer;display:flex;align-items:center;gap:6px;
      border-bottom:1px solid #13181f;white-space:nowrap}
.trow:hover{background:#161b22}
.tog{width:14px;color:#8b949e;cursor:pointer;user-select:none}
.tog.leaf{color:#30363d;cursor:default}
.tname{color:#79c0ff;font-weight:bold;flex:1;overflow:hidden;text-overflow:ellipsis}
.tdur{color:#8b949e;font-size:11px}
.tob{color:#f0883e;font-size:10px;border:1px solid #f0883e;padding:0 5px;border-radius:3px}
.terr{color:#f85149;font-size:11px;overflow:hidden;text-overflow:ellipsis;max-width:40ch}
#stats{padding:14px 18px;overflow:auto}
.cards{display:flex;gap:12px;margin-bottom:16px;flex-wrap:wrap}
.card{background:#161b22;border:1px solid #21262d;border-radius:6px;padding:10px 16px;min-width:110px}
.card .num{font-size:20px;color:#58a6ff;font-weight:bold}
.card .lbl{color:#8b949e;font-size:10px;text-transform:uppercase;letter-spacing:.06em}
.section-title{color:#8b949e;font-size:11px;text-transform:uppercase;letter-spacing:.08em;
               margin:14px 0 8px;border-bottom:1px solid #21262d;padding-bottom:4px}
.stat{width:100%;border-collapse:collapse;font-size:12px;margin-bottom:10px}
.stat th{color:#8b949e;text-align:left;font-size:10px;text-transform:uppercase;
         border-bottom:1px solid #30363d;padding:6px 8px}
.stat td{padding:5px 8px;border-bottom:1px solid #1c2128;color:#c9d1d9}
.stat tr:hover td{background:#161b22}
.num-err{color:#f85149;font-weight:bold}
.num-ok{color:#3fb950;font-weight:bold}
.diffkey{color:#e3b341}
#drawer{position:absolute;top:0;right:0;bottom:0;width:44%;min-width:420px;background:#0d1117;
        border-left:1px solid #30363d;z-index:10;overflow:hidden;transform:translateX(100%);
        transition:transform .18s ease;display:flex;flex-direction:column}
#drawer.open{transform:translateX(0)}
.d-head{display:flex;align-items:center;gap:10px;padding:10px 14px;border-bottom:1px solid #21262d}
.d-name{font-size:14px;font-weight:bold}
.d-status{padding:1px 8px;border-radius:3px;font-size:11px}
.d-status.st-done{background:#1c4828;color:#3fb950}
.d-status.st-error{background:#3d1d1d;color:#f85149}
.d-status.st-running{background:#1c3d6e;color:#58a6ff}
.d-meta{color:#8b949e;font-size:11px;padding:6px 14px;border-bottom:1px solid #21262d;display:flex;gap:16px}
.d-sec{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:#8b949e;
       padding:10px 14px 4px}
.d-pre{flex:1;overflow:auto;margin:0 14px 8px;padding:8px;background:#010409;border:1px solid #21262d;
       border-radius:4px;font-size:11px;white-space:pre-wrap;word-break:break-all;max-height:38%}
.d-log{flex:1;overflow:auto;padding:4px 14px 14px;font-size:11px}
.d-ev{padding:2px 0;white-space:pre-wrap;word-break:break-all}
.d-ev-checkpoint{color:#e3b341}
.d-ev-result{color:#56d364}
.d-ev-error{color:#f85149}
.d-ev-over_budget{color:#f0883e}
.d-ev-agent_response{color:#a5d6ff;border-left:2px solid #2f5e8a;padding-left:6px}
.d-ts{color:#444d56;user-select:none;margin-right:6px}
#replay-bar{display:none;background:#161b22;border-bottom:1px solid #21262d;padding:6px 14px;
            align-items:center;gap:12px;flex-shrink:0}
#replay-bar:not(:empty){display:flex}
.rp-ctl{display:flex;align-items:center;gap:10px;flex:1}
#rp-range{flex:1;accent-color:#58a6ff}
#rp-speed{background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:2px 6px;
          border-radius:4px;font-size:11px;font-family:inherit}
#cmp{flex:1;overflow:auto;padding:14px 18px}
.cmp-head{display:flex;gap:22px;margin-bottom:12px;color:#c9d1d9;flex-wrap:wrap}
#help{position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:20;display:none;align-items:center;justify-content:center}
#help.open{display:flex}
.help-card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:20px 26px;
           max-width:380px;line-height:1.9}
.help-card h2{color:#58a6ff;margin-bottom:8px}
.help-card button{margin-top:12px;background:#21262d;border:1px solid #30363d;color:#c9d1d9;
                  padding:4px 14px;border-radius:4px;cursor:pointer}
::-webkit-scrollbar{width:9px;height:9px}
::-webkit-scrollbar-thumb{background:#30363d;border-radius:4px}
</style>
</head>
<body>
<header>
  <h1 id="t-title">JSAT Dashboard</h1>
  <span id="timer-el">0s</span>
  <span id="status-pill" class="pill running">● LIVE</span>
  <div id="views">
    <button class="view-btn on" id="tab-waterfall" title="1">▤ Timeline</button>
    <button class="view-btn" id="tab-tree" title="2">☰ Tree</button>
    <button class="view-btn" id="tab-stats" title="3">Σ Stats</button>
  </div>
  <input id="filter-q" placeholder="filter calls…  ( / )" spellcheck="false">
  <select id="filter-status">
    <option value="all">all</option>
    <option value="running">running</option>
    <option value="done">done</option>
    <option value="error">error</option>
  </select>
  <button class="icon-btn" id="btn-expand" title="expand all (e)">+ all</button>
  <button class="icon-btn" id="btn-collapse" title="collapse all (c)">− all</button>
  <div id="spacer"></div>
  <button class="icon-btn" id="btn-help" title="help (?)">?</button>
</header>
<div id="replay-bar"></div>
<main>
  <div id="wf" class="pane">
    <div class="wf-toolbar"><span>Timeline</span><span id="wf-count" class="muted">—</span>
      <span class="muted">click a bar for args &amp; result</span></div>
    <div id="wf-ruler"></div>
    <div id="wf-area">
      <div id="wf-bars"></div>
      <div id="wf-cursor"></div>
    </div>
  </div>
  <div id="tree" class="pane hidden"></div>
  <div id="stats" class="pane hidden">
    <div class="cards">
      <div class="card"><div class="num" id="stat-calls">0</div><div class="lbl">calls</div></div>
      <div class="card"><div class="num" id="stat-running">0</div><div class="lbl">running</div></div>
      <div class="card"><div class="num" id="stat-errors">0</div><div class="lbl">errors</div></div>
      <div class="card"><div class="num" id="stat-over">0</div><div class="lbl">over budget</div></div>
      <div class="card"><div class="num" id="stat-total">0s</div><div class="lbl">total time</div></div>
    </div>
    <div id="sess-stats"></div>
    <div id="global-stats"></div>
  </div>
  <div id="cmp" class="hidden"></div>
  <div id="drawer">
    <div class="d-head">
      <span class="d-name">tool</span><span class="d-status">—</span>
      <div class="muted" style="flex:1"></div>
      <button class="icon-btn" id="drawer-close" title="close (Esc)">✕</button>
    </div>
    <div class="d-meta"><span>elapsed: <b class="d-elapsed">—</b></span>
      <span>budget: <b class="d-budget">—</b></span><span class="d-wall">—</span></div>
    <div class="d-sec">args</div><pre class="d-pre d-args"></pre>
    <div class="d-sec">result</div><pre class="d-pre d-payload"></pre>
    <div class="d-sec">event log</div><div class="d-log"></div>
  </div>
</main>
<div id="help"></div>
<script>
window.DASH = @INIT@;
</script>
<script>
@APP@
</script>
</body>
</html>
"""


def _page_html(init: dict) -> str:
    """Render the app page for a DASH init object (live session / replay / compare)."""
    return (_PAGE_SHELL
            .replace("@INIT@", json.dumps(init))
            .replace("@APP@", APP_JS))


_LANDING_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>JSAT Dashboard</title>
<noscript><meta http-equiv="refresh" content="5"></noscript>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0d1117;color:#c9d1d9;font-family:'Courier New',Courier,monospace;
     font-size:13px;padding:26px;max-width:900px;margin:0 auto}
h1{font-size:18px;color:#58a6ff;margin-bottom:4px}
.subtitle{color:#8b949e;font-size:12px;margin-bottom:22px}
.row{display:flex;align-items:center;justify-content:space-between;gap:12px;
     padding:9px 12px;border:1px solid #21262d;border-radius:5px;margin-bottom:6px;
     background:#161b22}
.row:hover{background:#1c2128}
.row a{color:#79c0ff;text-decoration:none;font-weight:bold;font-size:13px}
.row a:hover{text-decoration:underline}
.meta{margin-left:auto;color:#8b949e;font-size:11px;display:flex;gap:14px;align-items:center}
.badge{font-size:10px;padding:1px 8px;border-radius:9px}
.badge.running{color:#3fb950;border:1px solid #3fb950;animation:pulse 1.5s infinite}
.badge.done{color:#8b949e;border:1px solid #30363d}
.badge.err{color:#f85149;border:1px solid #f85149}
.ops a{color:#8b949e;font-size:11px;text-decoration:none;border:1px solid #30363d;
       padding:1px 7px;border-radius:4px;margin-left:6px}
.ops a:hover{color:#c9d1d9;background:#21262d}
.section{color:#8b949e;font-size:11px;text-transform:uppercase;letter-spacing:.08em;
         margin:18px 0 8px;border-bottom:1px solid #21262d;padding-bottom:4px}
.empty{color:#8b949e;font-style:italic;margin-top:10px}
code{background:#21262d;padding:1px 5px;border-radius:3px;font-size:12px}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
#stats-banner{margin-top:22px}
</style>
</head>
<body>
<h1>JSAT Dashboard</h1>
<div class="subtitle">http://localhost:<span class="port">0</span>/jsat/dashboard — live, replayable sessions</div>
<div id="active-title" class="section"></div>
<div id="active"></div>
<div id="arch-title" class="section"></div>
<div id="recent"></div>
<div id="stats-banner"></div>
<div class="empty">No sessions yet. Run <code>/jsat &lt;command&gt; dashboard=true &lt;task&gt;</code> to start one.</div>
<div style="margin-top:22px;color:#8b949e;font-size:11px">
  <a href="/jsat/dashboard/stats" style="color:#79c0ff">stats (JSON)</a> ·
  <a href="/jsat/dashboard/archive" style="color:#79c0ff">archive index (JSON)</a> ·
  replay: <code>/jsat/dashboard/replay?file=&lt;archive&gt;</code> ·
  compare: <code>/jsat/dashboard/compare?a=&lt;f&gt;&amp;b=&lt;f&gt;</code>
</div>
<script>
var BASE='/jsat/dashboard';
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
function fmt(s){if(s==null)return'—';if(s<60)return s.toFixed(1)+'s';var m=Math.floor(s/60);return m+'m '+Math.round(s-(m*60))+'s';}
function rows(list,active){
  var h='';
  (list||[]).forEach(function(it){
    var badge=active?'<span class="badge running">● RUNNING '+Math.round(it.elapsed_s)+'s</span>'
      :(it.errors?'<span class="badge err">'+it.errors+' err</span>'
         :'<span class="badge done">✓ '+fmt(it.elapsed_s)+'</span>');
    var ops='';
    if(it.archive)ops='<span class="ops"><a href="'+BASE+'/replay?file='+encodeURIComponent(it.archive)+'">▶ replay</a></span>';
    if(!active&&it.archive)ops+='<span class="ops"><a href="'+BASE+'/compare?b='+encodeURIComponent(it.archive)+'">⇄ compare</a></span>';
    h+='<div class="row"><a href="'+(it.url||(BASE+'/replay?file='+encodeURIComponent(it.archive)))+'">'+esc(it.name||it.slug)+'</a>'
      +'<span class="meta"><span>'+it.calls+' calls</span><span>'+esc(it.slug||'')+'</span>'+badge+'</span>'+ops+'</div>';
  });
  return h;
}
function render(d){
  if(!d)return;
  document.querySelector('.port').textContent=location.port||'7432';
  var a=document.getElementById('active'),at=document.getElementById('active-title'),
      r=document.getElementById('recent'),rt=document.getElementById('arch-title'),sb=document.getElementById('stats-banner');
  var act=d.active||[], rec=d.recent||[];
  at.textContent=act.length?('● Active Session'+(act.length>1?'s':'')):'';
  a.innerHTML=rows(act,true);
  rt.textContent=rec.length?('Sessions ('+rec.length+')'):'';
  r.innerHTML=rows(rec,false);
  sb.innerHTML='';
  if(d.stats){var t=d.stats.totals||{};
    sb.innerHTML='<div class="section">Across '+d.stats.sessions+' sessions</div>'
      +'<div class="muted" style="color:#8b949e">'+t.calls+' calls · '+t.errors+' errors · '
      +t.over_budget+' over budget · '+fmt(t.total_ms/1000)+' total</div>';
  }
  var empty=document.querySelector('.empty');
  if(act.length||rec.length)empty.style.display='none';
}
function refresh(){
  fetch(BASE+'/summary').then(function(x){return x.json();}).then(render).catch(function(){});
}
refresh();
setInterval(refresh,2000);
</script>
</body>
</html>
"""


def _html_landing(port: int) -> str:
    return _LANDING_HTML.replace('class="port">0<', f'class="port">{port}<')


# ── HTTP server ───────────────────────────────────────────────────────────────

class _DashboardHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


_BASE = "/jsat/dashboard"


class _DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        p = parsed.path
        q = parse_qs(parsed.query)

        if p in ("/jsat/dashboard", "/jsat/dashboard/"):
            self._send_html(_html_landing(_server_port or _PORT_DEFAULT))
            return

        if p == "/dashboard/session" or p.startswith("/dashboard/session"):
            dest = "/jsat/dashboard/" + p[len("/dashboard/session"):].strip("/")
            if dest in ("/jsat/dashboard/", "/jsat/dashboard"):
                dest = "/jsat/dashboard/"
            self._redirect(dest)
            return

        if p == "/events":
            self._redirect("/jsat/events")
            return

        if p == "/jsat/events":
            self._serve_sse(lambda: self._latest())
            return

        if p == f"{_BASE}/stats":
            self._send_json(_stats_document())
            return

        if p == f"{_BASE}/summary":
            self._send_json(self._summary_document())
            return

        if p == f"{_BASE}/compare":
            self._send_html(_page_html({"mode": "compare",
                                        "a": q.get("a", [""])[0],
                                        "b": q.get("b", [""])[0]}))
            return

        if p == f"{_BASE}/replay":
            self._send_html(_page_html({"mode": "replay",
                                        "file": q.get("file", [""])[0]}))
            return

        if p.startswith(f"{_BASE}/archive"):
            fname = p[len(f"{_BASE}/archive"):].strip("/")
            if not fname:
                self._send_json(_archive_list())
            else:
                self._serve_archive_file(fname)
            return

        if not p.startswith(_BASE + "/"):
            self._send_notfound()
            return

        # /jsat/dashboard/<slug>[/data|/events]
        rest = p[len(_BASE) + 1:].strip("/")
        parts = rest.split("/")
        slug = parts[0]
        sub = parts[1] if len(parts) > 1 else ""

        if sub == "events":
            self._serve_sse(lambda s=slug: _sessions.get(s))
            return
        if sub == "data":
            self._serve_snapshot(slug)
            return
        self._send_html(_page_html({"mode": "live", "slug": slug}))

    # ── response helpers ────────────────────────────────────────────────────

    def _latest(self) -> _DashboardSession | None:
        with _session_lock:
            slug = _latest_session_slug
            return _sessions.get(slug) if slug else None

    def _send_html(self, body: str, status: int = 200) -> None:
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, obj: Any, status: int = 200) -> None:
        data = json.dumps(obj, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_notfound(self, msg: str = "not found") -> None:
        self._send_json({"error": msg}, status=404)

    def _redirect(self, dest: str) -> None:
        self.send_response(301)
        self.send_header("Location", dest)
        self.end_headers()

    def _summary_document(self) -> dict:
        with _session_lock:
            active = [s for s in _sessions.values() if not s.is_done]
        active_rows = []
        for s in active:
            with s._lock:  # fast counts, no deep snapshot
                running = sum(1 for c in s.calls.values() if c.status == "running")
                errs = sum(1 for c in s.calls.values() if c.status == "error")
                n = len(s.calls)
            active_rows.append({
                "name": s.session_name, "slug": s.slug, "url": s.url,
                "elapsed_s": round(time.monotonic() - s.started_at, 1),
                "calls": n, "running": running, "errors": errs,
            })
        with _recent_sessions_lock:
            recent = list(reversed(_recent_sessions))
        arch = _archive_list()
        file_by_slug: dict[str, str] = {}
        for a in arch:
            file_by_slug.setdefault(a["slug"], a["file"])
        recent_rows = []
        scheduled = []
        for r in recent:
            file = file_by_slug.get(r.get("slug"), "")
            if file:
                scheduled.append(file)
            recent_rows.append({
                "name": r["name"], "slug": r.get("slug", ""), "file": file or "",
                "elapsed_s": r["elapsed_s"], "calls": r.get("calls", 0),
                "errors": r.get("errors", 0), "archive": file or None,
            })
        for a in arch:
            if a["file"] in scheduled:
                continue
            recent_rows.append({
                "name": a["session_name"], "slug": a["slug"], "file": a["file"],
                "elapsed_s": a.get("elapsed_s"), "calls": a.get("calls", 0),
                "errors": a.get("errors", 0), "archive": a["file"],
            })
        return {"active": active_rows, "recent": recent_rows,
                "stats": _stats_document(), "port": _server_port or _PORT_DEFAULT}

    def _serve_snapshot(self, slug: str) -> None:
        with _session_lock:
            sess = _sessions.get(slug)
        if sess is None:
            self._send_notfound(f"no dashboard session '{slug}'")
            return
        self._send_json(sess.snapshot())

    def _serve_archive_file(self, fname: str) -> None:
        name = Path(fname).name
        if name != fname or not name.endswith(".json"):
            self._send_notfound("bad archive filename")
            return
        path = _archive_dir() / name
        try:
            body = path.read_text(encoding="utf-8")
        except OSError:
            self._send_notfound(f"no archive '{name}'")
            return
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_sse(self, resolve: Callable[[], _DashboardSession | None]) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            self.wfile.write(b"retry: 2000\n\n")
            self.wfile.flush()
            sent = 0
            stall = 0.0
            while True:
                sess = resolve()
                if sess is None:
                    time.sleep(0.1)
                    stall += 0.1
                    if stall > 15.0:
                        return
                    continue
                stall = 0.0
                events = sess.events_snapshot()
                while sent < len(events):
                    ev = events[sent]
                    self.wfile.write(f"data: {json.dumps(ev)}\n\n".encode())
                    self.wfile.flush()
                    sent += 1
                    if ev.get("type") == "session_done":
                        return
                if sess.is_done:
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


def _start_idle_watcher(sess: _DashboardSession, slug: str) -> None:
    """Background thread: auto-fire session_done() after 30s of idle."""
    def _watch() -> None:
        while True:
            time.sleep(5)
            if sess.is_done:
                return
            all_done = sess.all_calls_finished()
            idle_s = time.monotonic() - sess.last_activity
            if all_done and idle_s > _IDLE_TIMEOUT:
                _log.info("dashboard_idle_timeout", session=sess.session_name,
                          idle_s=round(idle_s, 1))
                elapsed = round(time.monotonic() - sess.started_at, 1)
                sess.close(elapsed)
                _record_done(sess, elapsed)
                _schedule_session_reset(slug)
                return

    threading.Thread(target=_watch, daemon=True, name="jsat-dash-idle").start()


def _record_done(sess: _DashboardSession, elapsed_s: float) -> None:
    """Record a finished session in the landing ring and archive it to disk."""
    snap = sess.snapshot()
    entry = {
        "name": sess.session_name,
        "slug": sess.slug,
        "url": sess.url,
        "calls": len(snap["calls"]),
        "errors": sum(1 for c in snap["calls"].values() if c["status"] == "error"),
        "elapsed_s": elapsed_s,
        "ts": time.strftime("%H:%M:%S"),
    }
    with _recent_sessions_lock:
        _recent_sessions.append(entry)
        if len(_recent_sessions) > _MAX_RECENT_SESSIONS:
            _recent_sessions.pop(0)
    threading.Thread(target=_write_archive, args=(sess,), daemon=True,
                     name="jsat-dash-archive").start()


def _schedule_session_reset(slug: str) -> None:
    """Remove this session (by slug) after SHUTDOWN_DELAY so its URL eventually
    404s and a later reuse of the same name starts fresh. Other concurrently
    active sessions (different slugs) are untouched.
    """
    def _reset() -> None:
        global _latest_session_slug
        time.sleep(_SHUTDOWN_DELAY)
        with _session_lock:
            _sessions.pop(slug, None)
            if _latest_session_slug == slug:
                _latest_session_slug = None
            for cid in [c for c, s in _call_index.items() if s == slug]:
                _call_index.pop(cid, None)
        _log.debug("dashboard_session_cleared", session=slug)

    threading.Thread(target=_reset, daemon=True, name="jsat-dash-reset").start()


# ── Public API ────────────────────────────────────────────────────────────────

def start_dashboard(
    session_name: str,
    call_id: str,
    tool_name: str,
    parent_id: str | None,
    port: int = 7432,
    *,
    budget_s: float | None = None,
    mode: str = "default",
    args: str | None = None,
) -> tuple[str, bool]:
    """Register a tool call with the dashboard session.

    Args:
        session_name: The /jsat command name (e.g. "magic") — becomes URL slug.
        call_id:      UUID hex[:8] for this specific tool invocation.
        tool_name:    The MCP tool name (e.g. "query", "blast_radius").
        parent_id:    Parent call's call_id, or None for top-level calls.
        port:         HTTP port (default 7432).
        budget_s:     Soft budget in seconds, drawn as a marker on the waterfall.
        mode:         "default" | "plan" | "beast" — badged on the bar.
        args:         Serialized tool args (truncated server-side for storage).

    Returns (url, open_browser). open_browser=True only when a new session is created.
    """
    global _latest_session_slug

    slug = _slugify(session_name) or "session"

    if not _ensure_server(port):
        return f"http://localhost:{port}/jsat/dashboard/{slug}", False

    with _session_lock:
        sess = _sessions.get(slug)
        is_new_session = sess is None or sess.is_done

        if is_new_session:
            sess = _DashboardSession(session_name, port)
            _sessions[slug] = sess
            _start_idle_watcher(sess, slug)
            _log.info("dashboard_session_created", session=session_name, slug=slug, url=sess.url)
        else:
            _log.debug("dashboard_session_reuse", session=sess.session_name, call=call_id,
                       tool=tool_name)

        _latest_session_slug = slug
        _call_index[call_id] = slug

    sess.register_call(call_id, tool_name, parent_id,
                       budget_s=budget_s, mode=mode, args=args)

    if is_new_session:
        try:
            opened = webbrowser.open(sess.url)
            if not opened:
                _log.warning("dashboard_browser_open_failed", url=sess.url)
        except Exception as exc:
            _log.warning("dashboard_browser_open_error", url=sess.url, error=str(exc))

    return sess.url, is_new_session


def _session_for_call(call_id: str) -> _DashboardSession | None:
    """Resolve the session a given call_id belongs to, via the call_id index.

    Falls back to the most-recently-active session for pseudo call_ids (e.g. the
    deprecated push_event shim's "__session__" sentinel) never registered via
    start_dashboard().
    """
    with _session_lock:
        slug = _call_index.get(call_id) or _latest_session_slug
        return _sessions.get(slug) if slug else None


def push_call_event(call_id: str, event_type: str, msg: str, **extra: Any) -> None:
    """Push a typed event for a call. Thread-safe. No-op if no active session."""
    sess = _session_for_call(call_id)
    if sess is None or sess.is_done:
        return
    try:
        sess.push(call_id, event_type, msg, **extra)
    except Exception as exc:
        _log.warning("dashboard_push_failed", call_id=call_id, error=str(exc))


def finish_call(call_id: str, elapsed_s: float, status: str = "done") -> None:
    """Mark a call done. Tab stays open; idle timer handles session close."""
    sess = _session_for_call(call_id)
    if sess is None:
        return
    try:
        sess.finish(call_id, elapsed_s, status)
        _log.debug("dashboard_call_finished", call_id=call_id, elapsed_s=elapsed_s,
                   status=status)
    except Exception as exc:
        _log.warning("dashboard_finish_failed", call_id=call_id, error=str(exc))


def session_done(elapsed_s: float, call_id: str | None = None) -> None:
    """Mark the whole session done (called when /jsat command ends or on a
    single-tool call). Tab stays open; session is cleared after SHUTDOWN_DELAY
    and archived to disk for replay/comparison.

    `call_id` (when available) resolves which session to close, since several
    sessions may be active concurrently. Falls back to the most-recently-active
    session for older call sites that don't pass call_id.
    """
    with _session_lock:
        slug = _call_index.get(call_id) if call_id else _latest_session_slug
        sess = _sessions.get(slug) if slug else None
    if sess is None:
        return
    sess.close(elapsed_s)
    _record_done(sess, elapsed_s)
    _schedule_session_reset(slug)  # type: ignore[arg-type]


# ── Backward-compat shim (old callers used push_event / stop_dashboard) ──────

def push_event(type: str, msg: str, **extra: Any) -> None:  # noqa: A002
    """Deprecated shim — routes to push_call_event with a synthetic call_id."""
    with _session_lock:
        slug = _latest_session_slug
        sess = _sessions.get(slug) if slug else None
    if sess is None:
        return
    with sess._lock:
        running = [c for c in sess.calls.values() if c.status == "running"]
    cid = running[-1].call_id if running else "__session__"
    push_call_event(cid, type, msg, **extra)


def stop_dashboard(elapsed_s: float) -> None:
    """Deprecated shim — calls session_done()."""
    session_done(elapsed_s)