"""jsat._call_context — Shared per-call thread-local context and checkpoint helper.

Extracted from jsat.mcp.server so that tool files in jsat/tools/ can import
`checkpoint` without creating a circular dependency on server.py.
"""
from __future__ import annotations

import threading

# Thread-local context set by server.py for each MCP tool call.
# Fields set by the server:
#   events       list[str]    — recent substep labels (shown in timeout messages)
#   dashboard_push callable   — push_event(type, msg) → None, or None if no dashboard
#   call_id      str          — UUID hex[:8] for the current call (used for dashboard nesting)
#   sub_deadline float | None — monotonic deadline for nested budgets
#   depth        int          — call nesting depth
#   mode         str          — "default" | "plan" | "beast" (see _planner)
_call_ctx = threading.local()

_MODE_DEFAULT = "default"
_MODE_PLAN = "plan"
_MODE_BEAST = "beast"
MODES = (_MODE_DEFAULT, _MODE_PLAN, _MODE_BEAST)

# How much deeper nested tool calls may go in beast mode, and how much bigger
# every level's soft budget becomes. Kept here so tools that want to widen
# their own defaults (e.g. blast_radius max_depth) share one source of truth.
BEAST_DEPTH_LEEWAY = 5
BEAST_BUDGET_MULTIPLIER = 5.0


def call_mode() -> str:
    """Current call's mode — 'default', 'plan' or 'beast'. No-op outside a call."""
    return getattr(_call_ctx, "mode", _MODE_DEFAULT) or _MODE_DEFAULT


def in_beast_mode() -> bool:
    return call_mode() == _MODE_BEAST


def checkpoint(label: str) -> None:
    """Record a named substep.

    Appends the label to the current call's event log (surfaced in timeout
    messages as "last operations before kill") and pushes a 'checkpoint' event
    to the live dashboard if one is active. No-op when called outside an MCP
    call (e.g., in tests or CLI usage).
    """
    events: list | None = getattr(_call_ctx, "events", None)
    if events is not None:
        events.append(label)
    cb = getattr(_call_ctx, "dashboard_push", None)
    if cb is not None:
        cb("checkpoint", label)


def dashboard_only(label: str, event_type: str = "agent_response") -> None:
    """Push an event to the live dashboard only — not included in the timeout event log.

    Use for large text (e.g., full agent responses, synthesis outputs) that would be
    noisy in timeout messages but are valuable to show in the live tree.
    No-op when called outside an MCP call or when no dashboard is active.
    """
    cb = getattr(_call_ctx, "dashboard_push", None)
    if cb is not None:
        cb(event_type, label)
