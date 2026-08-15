"""jsat._improve._capture — friction-signal capture and the `jsat improve` nudge.

Design constraints:

* ``record_signal`` is called from ``except`` blocks. It must NEVER raise, or it
  would mask the very error it is recording. Its entire body is guarded, it
  returns ``None`` so no caller can depend on it, and it imports only stdlib.
* Zero cost on the happy path — signals are only produced when something has
  already gone wrong.
* No disk I/O in the hot path: records buffer in memory and flush on a threshold,
  a time interval, or at interpreter exit.
"""
from __future__ import annotations

import atexit
import os
import sys
import time
from typing import Any

_BUFFER: list[dict[str, Any]] = []
_SUPPRESSED: dict[str, int] = {}       # fingerprint -> occurrences not individually stored
_LAST_CLUSTER: dict[str, dict[str, Any]] = {}   # fingerprint -> record, for suppressed-only flushes
# Seeded from the clock so the interval check is relative to process start, not epoch.
_LAST_FLUSH = time.monotonic()
_LAST_PER_FP: dict[str, float] = {}
_RECORDED_THIS_PROCESS = 0
_ATEXIT_REGISTERED = False
_MODE = "cli"
_NUDGE_SUPPRESSED = False

_CFG_DEFAULTS: dict[str, Any] = {
    "enabled": True, "nudge": True, "threshold": 3,
    "cooldown": 86400, "no_telemetry": False,
}
_CFG: dict[str, Any] = dict(_CFG_DEFAULTS)

_FLUSH_EVERY = 10          # records
_FLUSH_INTERVAL_S = 60.0
_MAX_PER_PROCESS = 50
_PER_FP_THROTTLE_S = 1.0


def set_mode(mode: str) -> None:
    """Declare the host process type. ``"mcp"`` permanently disables the nudge."""
    global _MODE
    _MODE = mode


def set_config(cfg: Any) -> None:
    """Cache the improve/privacy settings from an already-loaded config.

    Called by ``JSAT.__init__``. Caching matters because the alternative — calling
    ``load_config()`` from the ``atexit`` handler — is both slow at shutdown and
    emits a ``config_loaded`` log line onto the user's stdout.
    """
    global _CFG
    try:
        improve = getattr(cfg, "improve", None)
        privacy = getattr(cfg, "privacy", None)
        _CFG = {
            "enabled": bool(getattr(improve, "enabled", True)),
            "nudge": bool(getattr(improve, "nudge", True)),
            "threshold": int(getattr(improve, "nudge_threshold", 3)),
            "cooldown": int(getattr(improve, "nudge_cooldown_s", 86400)),
            "no_telemetry": bool(getattr(privacy, "no_telemetry", False)),
        }
    except BaseException:
        pass


def suppress_nudge() -> None:
    """Disable the nudge for this process (structured/JSON output paths)."""
    global _NUDGE_SUPPRESSED
    _NUDGE_SUPPRESSED = True


def _capture_disabled() -> bool:
    """Cheap gates evaluated before any work."""
    if os.environ.get("JSAT_NO_IMPROVE"):
        return True
    return os.environ.get("CI", "").lower() in ("1", "true", "yes")


def _config_disabled() -> bool:
    """Config-based gates, read from the cache primed by ``set_config``.

    Defaults to enabled when no config has been seen — capture is local-only, and
    loading config here would be both slow and noisy.
    """
    return _CFG["no_telemetry"] or not _CFG["enabled"]


def record_signal(
    *, kind: str, source: str, exc: BaseException | None = None,
    op: str | None = None, detail: dict[str, Any] | None = None,
) -> None:
    """Record one friction signal about JSAT itself. Never raises, returns nothing.

    ``kind`` is one of ``crash`` | ``capability_gap`` | ``ux_friction`` |
    ``performance``. Nothing about the user's codebase is stored — see
    ``jsat._improve._sanitize`` for the guarantee.
    """
    global _RECORDED_THIS_PROCESS
    try:
        if _capture_disabled() or _RECORDED_THIS_PROCESS >= _MAX_PER_PROCESS:
            return

        from jsat._improve._sanitize import build_record
        record = build_record(kind=kind, source=source, exc=exc, op=op, detail=detail)
        if record is None:
            _note_dropped()
            return

        fp = record["fingerprint"]
        now = time.monotonic()
        last = _LAST_PER_FP.get(fp, 0.0)
        if now - last < _PER_FP_THROTTLE_S:
            # Tight retry loop: count it without paying for another record.
            _SUPPRESSED[fp] = _SUPPRESSED.get(fp, 0) + 1
            return
        _LAST_PER_FP[fp] = now

        _BUFFER.append(record)
        _LAST_CLUSTER[fp] = record
        _RECORDED_THIS_PROCESS += 1
        _register_atexit()

        if len(_BUFFER) >= _FLUSH_EVERY or (now - _LAST_FLUSH) > _FLUSH_INTERVAL_S:
            flush()
    except BaseException:  # noqa: BLE001 — must never mask the caller's exception
        pass


def _note_dropped() -> None:
    """Count privacy-filter rejections so `jsat improve` can report them honestly."""
    try:
        from jsat._improve._store import read_state, write_state
        state = read_state()
        state["dropped_count"] = int(state.get("dropped_count", 0)) + 1
        write_state(state)
    except BaseException:
        pass


def _register_atexit() -> None:
    global _ATEXIT_REGISTERED
    if _ATEXIT_REGISTERED:
        return
    try:
        atexit.register(_on_exit)
        _ATEXIT_REGISTERED = True
    except BaseException:
        pass


def flush() -> None:
    """Persist buffered records and fold them into clusters. Never raises."""
    global _LAST_FLUSH
    try:
        if _capture_disabled() or _config_disabled():
            _BUFFER.clear()
            _SUPPRESSED.clear()
            return
        if not _BUFFER and not _SUPPRESSED:
            return

        from jsat._improve._store import (
            append_signals,
            merge_cluster,
            read_clusters,
            write_clusters,
        )

        records = list(_BUFFER)
        _BUFFER.clear()
        suppressed = dict(_SUPPRESSED)
        _SUPPRESSED.clear()

        append_signals(records)

        clusters = read_clusters()
        for record in records:
            extra = suppressed.pop(record["fingerprint"], 0)
            clusters = merge_cluster(clusters, record, count=1 + extra)
        # Throttled repeats whose representative record flushed in an earlier batch
        # still have to be counted, or a tight retry loop reports as a single hit.
        for fp, extra in suppressed.items():
            template = _LAST_CLUSTER.get(fp)
            if template is not None and extra:
                clusters = merge_cluster(clusters, template, count=extra)
        write_clusters(clusters)
        _LAST_FLUSH = time.monotonic()
    except BaseException:
        pass


def _on_exit() -> None:
    """Flush, then maybe nudge. Fully swallowed — runs at interpreter shutdown."""
    try:
        had_signals = bool(_BUFFER) or _RECORDED_THIS_PROCESS > 0
        flush()
        if had_signals:
            _maybe_nudge()
    except BaseException:
        pass


def _maybe_nudge() -> None:
    """Print at most one line telling the dev that `jsat improve` may help.

    Conditions are ordered cheapest-first. The dual-TTY check is what keeps this
    out of MCP stdio, pipes, and `--json | jq`.
    """
    try:
        if _NUDGE_SUPPRESSED or _MODE == "mcp":
            return
        if os.environ.get("JSAT_NO_IMPROVE") or _capture_disabled():
            return
        if not (sys.stdout.isatty() and sys.stderr.isatty()):
            return

        from jsat._improve._store import read_clusters, read_state, write_state

        threshold, cooldown, enabled = _nudge_settings()
        if not enabled:
            return

        clusters = read_clusters()
        candidates = [
            c for c in clusters.values()
            if c.get("count", 0) >= threshold and not c.get("reported")
        ]
        if not candidates:
            return
        target = max(candidates, key=lambda c: c.get("count", 0))

        state = read_state()
        now = time.time()
        if now - float(state.get("last_nudge_ts", 0.0)) < cooldown:
            return
        fp = target["fingerprint"]
        counts = state.setdefault("nudge_counts", {})
        if int(counts.get(fp, 0)) >= 3:
            return

        counts[fp] = int(counts.get(fp, 0)) + 1
        state["last_nudge_ts"] = now
        write_state(state)

        label = target.get("exc_type") or target.get("kind") or "an issue"
        # Bare print, not Rich: Rich can touch closed streams at shutdown.
        print(
            f"\n\U0001f4a1 JSAT hit {label} {target.get('count', 0)}x "
            f"and may be able to fix itself — run: jsat improve",
            file=sys.stderr,
        )
    except BaseException:
        pass


def _nudge_settings() -> tuple[int, int, bool]:
    return _CFG["threshold"], _CFG["cooldown"], _CFG["nudge"] and _CFG["enabled"]


def _reset_for_tests() -> None:
    """Clear module state between tests."""
    global _LAST_FLUSH, _RECORDED_THIS_PROCESS, _MODE, _NUDGE_SUPPRESSED, _CFG
    _BUFFER.clear()
    _SUPPRESSED.clear()
    _LAST_PER_FP.clear()
    _LAST_CLUSTER.clear()
    _LAST_FLUSH = time.monotonic()
    _RECORDED_THIS_PROCESS = 0
    _MODE = "cli"
    _NUDGE_SUPPRESSED = False
    _CFG = dict(_CFG_DEFAULTS)
