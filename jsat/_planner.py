"""jsat._planner — propose-then-approve planning (``mode=plan``) for any JSAT call.

A ``mode=plan`` MCP call is intercepted in ``MCPServer._handle`` before the
executor is ever submitted: **nothing runs**. JSAT returns a structured plan
and persists it as a ``_sessions.Session`` (``skill=plan``, ``status=proposed``)
plus a JSON sidecar holding the exact tool + args per step.

Approval is a separate surface:
  * MCP  — ``execute_plan(plan_id=..., tool=..., args=...)``
  * CLI  — ``jsat plan list | show | approve | run | discard``

Steps are grouped by the ``_dashboard_session`` key when the caller supplies
one, so an AI composing a whole-task plan can send several ``mode=plan`` probes
that accumulate into a single proposal instead of one throwaway file per call.
Each step names the tool, the args it would receive, and a classification of
what it touches (graph write / AI token spend / read + compute), so a human can
approve knowing exactly what the plan commits to.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import _sessions

PLAN_SKILL = "plan"

# ── step classification ───────────────────────────────────────────────────────
# A plan must say what each step will touch. Classify every tool as a graph/KB
# write, an AI-provider token spend, or a pure read/compute.
_WRITE_TOOLS = frozenset({
    "index_repo", "create_index_md", "export_index", "import_index",
    "knowledge_add", "knowledge_flag_stale",
})
_TOKEN_TOOLS = frozenset({
    "query", "short", "crack", "submit_for_review", "get_review_findings",
    "generate_unit_test", "generate_integration_test", "generate_contract_test",
    "prompt_optimize", "prompt_rewrite", "prompt_multi_agent", "prompt_diff",
    "security_review", "investigate_incident", "generate_runbook",
    "ithinking_plan", "ithinking_execute", "ithinking_audit_assumptions",
    "ithinking_reflect", "ithinking_token_estimate",
})


def classify(tool: str) -> str:
    """What executing this tool touches: write | token-spend | read/compute."""
    if tool in _WRITE_TOOLS:
        return "graph_or_kb_write"
    if tool in _TOKEN_TOOLS:
        return "ai_or_token_spend"
    return "read_or_compute"


# ── persistence ───────────────────────────────────────────────────────────────

def _plan_path(key: str) -> Path:
    return _sessions.sessions_dir() / f"plan-{_sessions.slugify(key, words=6)}.md"


def _meta_path(session: _sessions.Session) -> Path:
    return session.path.with_suffix(".plan.json")


def _read_meta(session: _sessions.Session) -> dict[str, Any]:
    try:
        doc = json.loads(_meta_path(session).read_text(encoding="utf-8"))
        if isinstance(doc, list):  # tolerate an old flat-list sidecar
            return {"key": session.task.replace("Plan for: ", ""), "steps": doc}
        return doc
    except Exception:
        return {"key": "", "steps": []}


def _write_meta(session: _sessions.Session, key: str, steps: list[dict[str, Any]]) -> None:
    session.path.parent.mkdir(parents=True, exist_ok=True)
    _meta_path(session).write_text(
        json.dumps({"key": key, "steps": steps}, indent=2, default=str),
        encoding="utf-8",
    )


def _load_or_create(key: str) -> _sessions.Session:
    session = load_plan(key)
    if session is None:
        session = _sessions.Session(
            skill=PLAN_SKILL,
            task=f"Plan for: {key}",
            path=_plan_path(key),
            status="proposed",
        )
        session.save()
        _write_meta(session, key, [])
    return session


def load_plan(key_or_id: str) -> _sessions.Session | None:
    """Load a plan by its session key or a filename fragment. Tolerant."""
    key = key_or_id or ""
    candidates = list_plans()
    for session in candidates:
        if session.path.name == f"plan-{_sessions.slugify(key, words=6)}.md":
            return session
        if key in session.path.name:
            return session
    return None


def list_plans() -> list[_sessions.Session]:
    """All plan sessions, newest first (status 'proposed' or later)."""
    return [
        s for s in _sessions.list_sessions(skill=PLAN_SKILL, limit=200)
        if s.status in ("proposed", "in_progress", "completed", "rejected")
    ]


# ── building ──────────────────────────────────────────────────────────────────

def _step_name(tool: str, args: dict[str, Any]) -> str:
    summary = ", ".join(f"{k}={_short(v)}" for k, v in args.items()) or "no args"
    return f"{tool} ({summary})"


def _short(value: Any, limit: int = 48) -> str:
    text = str(value)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def append_step(key: str, tool: str, args: dict[str, Any], budget: float) -> dict:
    """Record one planned call onto plan ``key`` and return the snapshot dict."""
    name = _step_name(tool, args)
    session = _load_or_create(key)
    meta = _read_meta(session)
    for step in session.steps:
        if step.name == name and not step.done:
            return snapshot_plan(session)
    session.steps.append(_sessions.Step(name=name, done=False))
    meta["steps"].append({
        "name": name,
        "tool": tool,
        "args": args,
        "kind": classify(tool),
        "budget_s": budget,
    })
    session.task = f"Plan for: {key} ({len(session.steps)} steps)"
    session.save()
    _write_meta(session, key, meta["steps"])
    return snapshot_plan(session)


def snapshot_plan(session: _sessions.Session) -> dict[str, Any]:
    """The structured, human-readable plan payload returned to the caller."""
    meta = _read_meta(session)
    by_name = {m["name"]: m for m in meta["steps"]}
    steps = [{
        "step": i + 1,
        "tool": (by_name[s.name].get("tool") if s.name in by_name else ""),
        "args": (by_name[s.name].get("args") if s.name in by_name else {}),
        "kind": (by_name[s.name].get("kind") if s.name in by_name else ""),
        "done": s.done,
    } for i, s in enumerate(session.steps)]
    return {
        "_mode": "plan",
        "plan_id": session.path.stem,
        "plan_file": str(session.path),
        "key": meta.get("key", ""),
        "status": session.status,
        "nothing_executed": True,
        "steps": steps,
        "ai_guidance": (
            "Nothing was executed. Send more _mode='plan' probes with the same "
            "_dashboard_session key to append steps, then approve with "
            "execute_plan(plan_id='" + session.path.stem + "') or "
            "'jsat plan run <id>' to execute."
        ),
    }


# ── execution (the approval step) ─────────────────────────────────────────────

def execute_plan(
    session: _sessions.Session,
    dispatch: Callable[[str, dict[str, Any]], Any],
    step_callback: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Run every pending step of an approved plan through ``dispatch(tool, args)``.

    ``dispatch`` is the server-side tool dispatcher (``MCPServer._call``) or a
    thin CLI adapter. Each step result is truncated and recorded on the session
    step; failures are recorded as findings and never crash the whole run.
    """
    meta = {m["name"]: m for m in _read_meta(session).get("steps", [])}
    session.status = "in_progress"
    session.save()

    results: list[dict[str, Any]] = []
    errors = 0
    pending = [s for s in session.steps if not s.done]
    total = len(pending)
    for pos, step in enumerate(pending, start=1):
        m = meta.get(step.name, {})
        tool = m.get("tool", "")
        args = m.get("args", {})
        if step_callback:
            step_callback(pos, total)
        try:
            raw = dispatch(tool, args) if tool else None
            text = str(raw) if not isinstance(raw, dict) else json.dumps(raw, default=str)
            result = _short(text, limit=300)
        except Exception as exc:  # degrade, never crash the whole plan
            errors += 1
            result = f"ERROR: {_short(str(exc), limit=200)}"
        results.append({
            "step": pos,
            "tool": tool,
            "kind": m.get("kind", classify(tool)),
            "ok": not result.startswith("ERROR"),
            "result": result,
        })
        session.complete_step(step.name, result[:140])

    session.finish("completed")
    return {
        "plan_id": session.path.stem,
        "status": "completed",
        "steps_run": len(results),
        "errors": errors,
        "results": results,
        "note": "All steps executed. Run 'jsat plan show " + session.path.stem
                + "' to review the recorded findings.",
    }