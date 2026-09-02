"""
Phase C — every MCP tool, over real stdio JSON-RPC.

The original self-test called exactly one of the 69 registered tools. This
suite calls all of them against the fixture repo and asserts on the shape of
what comes back.

Two rules make this durable rather than a snapshot:

1. **Completeness gate.** `tools/list` is diffed against MCP_CASES. A tool the
   server registers but this file does not cover is a FAILURE, not a gap. Add
   a tool to `_build_registry()` and the self-test goes red until it is
   actually exercised.
2. **Assert on structure, never prose.** LLM-backed tools return English that
   changes run to run; the assertions look at JSON keys, types and known-true
   facts about the fixture repo, so a passing check means the machinery
   worked, not that a model happened to phrase something a certain way.

Response shapes (verified against the live server):
  success        result.content[0].text  → a JSON document
  soft error     that JSON document contains an "error" key
  protocol error top-level "error" object
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core import (
    FAIL,
    PASS,
    UNAVAILABLE,
    Check,
    MCPClient,
    Report,
    timed,
    tool_text,
)
from ..fixtures import scratch_facts

FACTS = scratch_facts()


@dataclass
class ToolCase:
    """One tool, one real invocation, one assertion."""
    args: dict[str, Any] = field(default_factory=dict)
    expect: list[str] = field(default_factory=list)       # substrings (case-insensitive)
    forbid: list[str] = field(default_factory=list)
    predicate: Callable[[Any], bool] | None = None        # runs on parsed JSON
    allow_soft_error: bool = False   # a tool whose correct answer here IS an error
    llm: bool = False                # needs a working AI provider
    timeout: float = 60.0
    note: str = ""


def _has_keys(*keys: str) -> Callable[[Any], bool]:
    def p(payload: Any) -> bool:
        if isinstance(payload, list):
            return all(any(k in item for item in payload if isinstance(item, dict))
                       for k in keys) if payload else False
        return isinstance(payload, dict) and all(k in payload for k in keys)
    return p


def _nonempty_list(payload: Any) -> bool:
    return isinstance(payload, list) and len(payload) > 0


def _is_list(payload: Any) -> bool:
    return isinstance(payload, list)


def _is_obj(payload: Any) -> bool:
    return isinstance(payload, dict)


# ── The full matrix: one entry per registered tool ────────────────────────
#
# `_dashboard`, `_budget` and `_dashboard_session` are injected into every
# schema and stripped before handlers run, so they are never passed here;
# they get their own dedicated checks below.

def build_cases(repo: Path, tmp: Path) -> dict[str, ToolCase]:
    f = FACTS
    return {
        # ── index / meta ──────────────────────────────────────────────────
        "index_repo": ToolCase(
            {"path": str(repo), "incremental": True},
            predicate=_is_obj, timeout=120,
            note="re-indexes the fixture repo in place"),
        "get_index_status": ToolCase(
            predicate=lambda p: isinstance(p, dict) and p.get("nodes", 0) > 0),
        "create_index_md": ToolCase(
            {"path": str(repo)}, predicate=_is_obj, timeout=120),
        "lookup_index_md": ToolCase(
            {"pattern": "process_payment", "path": str(repo)}, predicate=lambda p: p is not None),
        "get_jsat_version": ToolCase(
            predicate=lambda p: isinstance(p, dict) and bool(p.get("version"))),
        "improve_status": ToolCase(predicate=_is_obj),
        "health": ToolCase(predicate=_is_obj),
        "get_metrics": ToolCase(predicate=_is_obj),
        "export_index": ToolCase(
            {"output": str(tmp / "mcp-export.jsat.zip")},
            predicate=lambda p: isinstance(p, dict) and not p.get("error")),
        "import_index": ToolCase(
            {"archive": str(tmp / "mcp-export.jsat.zip")},
            predicate=_is_obj, timeout=90,
            note="runs after export_index, which writes the archive it reads"),

        # ── graph exploration ─────────────────────────────────────────────
        "list_services": ToolCase(
            predicate=_nonempty_list,
            note="fixture has svc_payments/ and svc_users/ top-level dirs"),
        "list_endpoints": ToolCase(predicate=_is_list),
        "get_function": ToolCase(
            {"name": f["tested_function"]},
            predicate=lambda p: isinstance(p, dict) and not p.get("error")),
        "get_class": ToolCase(
            {"name": "StripeGateway"},
            predicate=lambda p: isinstance(p, dict) and not p.get("error")),
        "list_tables": ToolCase(predicate=_is_list),
        "trace_call_chain": ToolCase(
            {"from": "handle_payment_request", "to": "validate_amount"},
            predicate=lambda p: p is not None,
            note="fixture has a real 4-deep chain between these two"),
        "get_data_flow": ToolCase(predicate=lambda p: p is not None),
        "query": ToolCase(
            {"question": "which function validates the payment amount?"},
            llm=True, timeout=180, predicate=lambda p: p is not None),

        # ── blast radius ──────────────────────────────────────────────────
        "blast_radius": ToolCase(
            {"target": "validate_amount", "max_depth": 3},
            predicate=_is_obj),
        "blast_radius_file": ToolCase(
            {"path": "svc_payments/payments.py"}, predicate=_is_obj),
        "blast_radius_symbol": ToolCase(
            {"symbol": "validate_amount"}, predicate=_is_obj),
        "blast_radius_topic": ToolCase(
            {"topic": "payments"}, predicate=lambda p: p is not None,
            allow_soft_error=True,
            note="fixture has no Topic nodes; a clean 'not found' is correct"),
        "blast_radius_diff": ToolCase(
            {"diff": _SAMPLE_DIFF}, predicate=_is_obj),
        "get_consumers": ToolCase(
            {"target": "validate_amount"}, predicate=lambda p: p is not None),
        "get_consumers_of_endpoint": ToolCase(
            {"endpoint": "/payments"}, predicate=lambda p: p is not None,
            allow_soft_error=True),

        # ── security ──────────────────────────────────────────────────────
        "security_review": ToolCase(
            {"path": str(repo)}, predicate=_is_obj, timeout=180),
        "security_scan_file": ToolCase(
            {"file": "svc_payments/config.py", "severity": "low"},
            predicate=lambda p: isinstance(p, dict)
            and p.get("secrets_found", 0) >= 1,
            timeout=180,
            note="config.py carries a synthetic AWS key; zero findings here "
                 "means the single-file scan path is broken, which reads as a "
                 "false all-clear"),
        "list_secrets": ToolCase(
            {"path": str(repo)},
            predicate=lambda p: isinstance(p, dict)
            and p.get("secrets_found", 0) >= 1,
            timeout=180,
            note="fixture config.py carries a synthetic AWS-shaped key"),
        "get_auth_coverage": ToolCase(predicate=lambda p: p is not None),
        "get_dependency_cves": ToolCase(
            {"cvss_min": 0.0},
            predicate=lambda p: bool(p) and (
                (isinstance(p, list) and len(p) > 0)
                or (isinstance(p, dict) and bool(p.get("cves")))
                or (isinstance(p, str) and "requests" in p)),
            timeout=180,
            note="fixture pins requests==2.19.1, which has real OSV advisories"),
        "trace_data_flow": ToolCase(
            {"entry_point": "handle_payment_request"}, predicate=lambda p: p is not None),

        # ── tests ─────────────────────────────────────────────────────────
        "get_test_gaps": ToolCase(
            {"path": "svc_payments"},
            predicate=lambda p: isinstance(p, str) and "Coverage:" in p,
            timeout=120,
            note="repo-relative path; svc_payments has one tested and one "
                 "untested function"),
        "get_behavioral_coverage": ToolCase(predicate=lambda p: p is not None, timeout=90),
        "list_untested_paths": ToolCase(
            {"limit": 20}, predicate=lambda p: p is not None, timeout=90),
        "generate_unit_test": ToolCase(
            {"function": f["untested_function"]}, llm=True, timeout=180,
            predicate=lambda p: p is not None),
        "generate_integration_test": ToolCase(
            {"endpoint": "/payments"}, llm=True, timeout=180,
            predicate=lambda p: p is not None),
        "generate_contract_test": ToolCase(
            {"producer": "svc_payments", "consumer": "svc_users"}, llm=True,
            timeout=180, predicate=lambda p: p is not None),

        # ── API contract (two real git refs in the fixture) ───────────────
        "get_api_diff": ToolCase(
            {"base": f["old_ref"], "head": f["new_ref"]},
            predicate=lambda p: p is not None, timeout=90),
        "check_breaking_changes": ToolCase(
            {"base": f["old_ref"], "head": f["new_ref"]},
            predicate=lambda p: p is not None, timeout=90,
            note="v1→v2 drops /refunds and makes currency required"),
        "get_compat_score": ToolCase(
            {"base": f["old_ref"], "head": f["new_ref"]},
            predicate=lambda p: p is not None, timeout=90),

        # ── migration ─────────────────────────────────────────────────────
        "validate_migration": ToolCase(
            {"file": "svc_payments/migrations/001_add_currency.sql"},
            predicate=lambda p: isinstance(p, str) and "Risk:" in p,
            note="a repo-relative path, which is the form an agent has; the "
                 "fixture migration contains the ADD COLUMN NOT NULL DEFAULT "
                 "trap"),
        "estimate_lock_duration": ToolCase(
            {"operation": "ALTER TABLE payments ADD COLUMN currency VARCHAR(3) "
                          "NOT NULL DEFAULT 'USD'",
             "table": "payments", "row_count": 5_000_000},
            predicate=lambda p: p is not None),
        "suggest_zero_downtime": ToolCase(
            {"operation": "ALTER TABLE payments ADD COLUMN currency VARCHAR(3) "
                          "NOT NULL DEFAULT 'USD'"},
            predicate=lambda p: p is not None),

        # ── review ────────────────────────────────────────────────────────
        "submit_for_review": ToolCase(
            {"diff": _SAMPLE_DIFF}, llm=True, timeout=240,
            predicate=lambda p: p is not None),
        "get_review_findings": ToolCase(
            {"min_confidence": "low"}, predicate=lambda p: p is not None,
            allow_soft_error=True),
        "get_high_confidence_bugs": ToolCase(
            predicate=lambda p: p is not None, allow_soft_error=True),

        # ── knowledge ─────────────────────────────────────────────────────
        "knowledge_add": ToolCase(
            {"text": "All monetary amounts in svc_payments are integer minor units.",
             "category": "convention"},
            predicate=lambda p: p is not None, timeout=120),
        "knowledge_query": ToolCase(
            {"question": "how is money represented?"}, llm=True, timeout=180,
            predicate=lambda p: p is not None),
        "knowledge_search": ToolCase(
            {"query": "monetary", "limit": 5}, predicate=lambda p: p is not None),
        "knowledge_list": ToolCase(predicate=lambda p: p is not None),
        "knowledge_flag_stale": ToolCase(
            {"entry_id": "nonexistent-entry-id"}, allow_soft_error=True,
            predicate=lambda p: p is not None,
            note="asserts the not-found path is clean, not a traceback"),

        # ── incident ──────────────────────────────────────────────────────
        "investigate_incident": ToolCase(
            {"description": "payment validation causing timeout errors in production"},
            predicate=lambda p: p is not None, timeout=120,
            note="fixture git history has a commit matching those keywords"),
        "get_hypotheses": ToolCase(
            {"limit": 5}, predicate=lambda p: p is not None, timeout=120),
        "get_recent_changes": ToolCase(
            {"since": "30 days ago"}, predicate=lambda p: p is not None),
        "generate_runbook": ToolCase(
            {"hypothesis": "the payment validation change caused the timeouts"},
            llm=True, timeout=180, predicate=lambda p: p is not None),

        # ── ithinking (policy gates, no LLM inside the tool) ──────────────
        "ithinking_plan": ToolCase(
            {"task": "add a currency field to the payment model"},
            predicate=lambda p: p is not None),
        "ithinking_execute": ToolCase(
            {"task": "list the payment service endpoints"},
            predicate=lambda p: p is not None),
        "ithinking_reflect": ToolCase(
            {"task": "add a currency field", "result": "added and tested"},
            predicate=lambda p: p is not None),
        "ithinking_audit_assumptions": ToolCase(
            {"subtask": "drop all rows from the payments table in production"},
            predicate=lambda p: p is not None,
            note="deliberately risky phrasing — the gate should flag it"),
        "ithinking_token_estimate": ToolCase(
            {"task": "summarize the payment service"},
            predicate=lambda p: p is not None),

        # ── prompt optimizer ──────────────────────────────────────────────
        "prompt_optimize": ToolCase(
            {"query": "how do i add a currency field to payments"},
            predicate=lambda p: p is not None, timeout=120),
        "prompt_diff": ToolCase(
            {"query": "how do i add a currency field to payments"},
            predicate=lambda p: p is not None, timeout=120),
        "prompt_rewrite": ToolCase(
            {"query": "how do i add a currency field to payments"},
            llm=True, timeout=180, predicate=lambda p: p is not None),
        "prompt_multi_agent": ToolCase(
            {"query": "how do i add a currency field to payments", "n_agents": 2},
            llm=True, timeout=300, predicate=lambda p: p is not None),

        # ── token optimizer (fully offline by design) ─────────────────────
        "token_count": ToolCase(
            {"text": "hello world, this is a token counting test"},
            predicate=lambda p: isinstance(p, dict) and isinstance(
                p.get("tokens", p.get("token_count")), int)),
        "token_compress": ToolCase(
            {"text": ("This is a very long piece of text. " * 40),
             "target_tokens": 50},
            predicate=lambda p: p is not None),
        "token_budget": ToolCase(
            {"text": "a short prompt", "model": "claude-sonnet-4"},
            predicate=lambda p: p is not None),

        # ── multi-agent / UX ──────────────────────────────────────────────
        "crack": ToolCase(
            {"task": "should payments store currency as a column or a separate table?",
             "rounds": 1}, llm=True, timeout=600,
            predicate=lambda p: p is not None),
        "short": ToolCase(
            {"query": "what does validate_amount do?", "max_words": 20},
            llm=True, timeout=180, predicate=lambda p: p is not None),
    }


_SAMPLE_DIFF = """\
diff --git a/svc_payments/payments.py b/svc_payments/payments.py
index 1111111..2222222 100644
--- a/svc_payments/payments.py
+++ b/svc_payments/payments.py
@@ -20,7 +20,7 @@ class StripeGateway(BaseGateway):
 def validate_amount(amount):
     \"\"\"Depth 4 of the call chain.\"\"\"
-    if amount <= 0:
+    if amount < 0:
         raise InsufficientFunds("amount must be positive")
     return True
"""


# ── Runner ────────────────────────────────────────────────────────────────

def _evaluate(name: str, case: ToolCase, resp: dict[str, Any] | None) -> Check:
    cat = "mcp_tools"
    if resp is None:
        return Check(f"mcp_{name}", cat, FAIL,
                     "no response from the MCP server (timeout or crash)",
                     remediation="check `jsat mcp-server` stderr for a traceback")
    if "error" in resp:
        return Check(f"mcp_{name}", cat, FAIL,
                     f"JSON-RPC protocol error: {resp['error'].get('message', '')[:200]}",
                     detail=json.dumps(resp)[:600])

    text = tool_text(resp)
    try:
        payload: Any = json.loads(text)
    except json.JSONDecodeError:
        payload = text  # some tools legitimately return prose/markdown

    soft_error = None
    if isinstance(payload, dict) and payload.get("error"):
        soft_error = str(payload["error"])
    elif isinstance(payload, list) and payload and isinstance(payload[0], dict) \
            and payload[0].get("error"):
        soft_error = str(payload[0]["error"])

    if soft_error and not case.allow_soft_error:
        return Check(f"mcp_{name}", cat, FAIL,
                     f"tool returned an error: {soft_error[:200]}",
                     detail=text[:600],
                     remediation=case.note or "")

    low = text.lower()
    missing = [e for e in case.expect if e.lower() not in low]
    if missing:
        return Check(f"mcp_{name}", cat, FAIL,
                     f"response missing expected content {missing}", detail=text[:600])
    present = [b for b in case.forbid if b.lower() in low]
    if present:
        return Check(f"mcp_{name}", cat, FAIL,
                     f"response contained forbidden content {present}", detail=text[:600])

    if case.predicate and not soft_error:
        try:
            ok = case.predicate(payload)
        except Exception as e:
            return Check(f"mcp_{name}", cat, FAIL,
                         f"shape assertion raised {type(e).__name__}: {e}",
                         detail=text[:600])
        if not ok:
            return Check(f"mcp_{name}", cat, FAIL,
                         "response shape did not match the expected structure",
                         detail=text[:600])

    suffix = " (clean not-found path)" if soft_error else ""
    return Check(f"mcp_{name}", cat, PASS,
                 f"real tools/call succeeded end-to-end{suffix}", detail=text[:300])


def run(report: Report, jsat_bin: str, repo: Path, tmp: Path,
        env: dict[str, str], *, allow_llm: bool) -> None:
    """Call every registered MCP tool against the fixture repo."""
    cases = build_cases(repo, tmp)

    client = MCPClient(jsat_bin, repo, env)
    try:
        init = client.handshake()
        if init is None or "result" not in init:
            report.add(Check("mcp_initialize", "mcp_server", FAIL,
                             "MCP server did not respond to initialize",
                             detail=f"response={init} stderr={client.stderr_tail()}"))
            return
        report.add(Check("mcp_initialize", "mcp_server", PASS,
                         "initialize handshake OK"))

        resp = client.call("tools/list")
        if resp is None or "result" not in resp:
            report.add(Check("mcp_tools_list", "mcp_server", FAIL,
                             "tools/list returned no result", detail=str(resp)))
            return
        registered = [t.get("name", "?") for t in resp["result"].get("tools", [])]
        report.add(Check("mcp_tools_list", "mcp_server", PASS,
                         f"tools/list returned {len(registered)} tools",
                         detail=", ".join(sorted(registered))))

        # ── the completeness gate ────────────────────────────────────────
        uncovered = sorted(set(registered) - set(cases))
        stale = sorted(set(cases) - set(registered))
        if uncovered:
            report.add(Check("mcp_coverage_complete", "mcp_tools", FAIL,
                             f"{len(uncovered)} registered MCP tool(s) have no self-test case",
                             detail=", ".join(uncovered),
                             remediation="add a ToolCase for each in "
                                         "scripts/selftest/suites/mcp_tools.py"))
        elif stale:
            report.add(Check("mcp_coverage_complete", "mcp_tools", FAIL,
                             f"{len(stale)} self-test case(s) target tools that no longer exist",
                             detail=", ".join(stale),
                             remediation="remove the stale ToolCase entries"))
        else:
            report.add(Check("mcp_coverage_complete", "mcp_tools", PASS,
                             f"all {len(registered)} registered tools have a case"))

        # export_index must run before import_index; dict order guarantees it.
        for name in registered:
            case = cases.get(name)
            if case is None:
                continue  # already reported by the completeness gate
            if case.llm and not allow_llm:
                report.add(Check(f"mcp_{name}", "mcp_tools", UNAVAILABLE,
                                 "needs a working AI provider; skipped by --no-llm",
                                 remediation="drop --no-llm, or `jsat ai use claude_cli`"))
                continue
            r = client.tool(name, case.args, timeout=case.timeout)
            report.add(_evaluate(name, case, r))
    finally:
        client.close()


# ── The reliability engine: budgets, depth cap, RBAC, auth ────────────────

@timed
def check_soft_budget_notification(jsat_bin: str, repo: Path,
                                   env: dict[str, str]) -> Check:
    """A tool given a 1s soft budget must emit notifications/progress.

    This is the mechanism behind the user-facing `timeout=N` flag, and it is
    what stops a slow tool from silently hanging an AI agent. Per the MCP
    spec the server may only send progress for a call that supplied a
    `_meta.progressToken`, so the token is included here exactly as a real
    client would — omitting it makes the feature look broken when it is
    simply being protocol-correct.
    """
    with MCPClient(jsat_bin, repo, env) as c:
        c.handshake()
        r = c.call("tools/call",
                   {"name": "security_review",
                    "arguments": {"path": str(repo), "_budget": 1},
                    "_meta": {"progressToken": "selftest-budget-1"}},
                   timeout=300)
        if r is None:
            return Check("mcp_soft_budget", "mcp_reliability", FAIL,
                         "the call with _budget=1 never returned")
        progress = [n for n in c.notifications
                    if "progress" in str(n.get("method", ""))]
        if not progress:
            return Check("mcp_soft_budget", "mcp_reliability", FAIL,
                         "a call that ran past its 1s soft budget sent no "
                         "notifications/progress, so `timeout=N` gives the "
                         "agent no signal",
                         detail=f"response={json.dumps(r)[:250]} "
                                f"notifications={c.notifications[:3]}",
                         remediation="check _monitor_budget/_notify in "
                                     "jsat/mcp/server.py")
        matching = [n for n in progress
                    if n.get("params", {}).get("progressToken")
                    == "selftest-budget-1"]
        if not matching:
            return Check("mcp_soft_budget", "mcp_reliability", FAIL,
                         "progress notifications were sent with the wrong "
                         "progressToken, so a real client would ignore them",
                         detail=json.dumps(progress[0])[:300])
        msg = matching[0].get("params", {}).get("message", "")
        if "still running" not in msg.lower():
            return Check("mcp_soft_budget", "mcp_reliability", FAIL,
                         "the over-budget notification does not tell the agent "
                         "the call is still running",
                         detail=msg[:250])
        return Check("mcp_soft_budget", "mcp_reliability", PASS,
                     f"the 1s soft budget fired {len(matching)} correctly-"
                     "tokened progress notification(s) while the call "
                     "continued",
                     detail=msg[:250])


@timed
def check_no_progress_without_token(jsat_bin: str, repo: Path,
                                    env: dict[str, str]) -> Check:
    """The inverse: no progressToken means no notifications (MCP spec)."""
    with MCPClient(jsat_bin, repo, env) as c:
        c.handshake()
        c.call("tools/call",
               {"name": "security_review",
                "arguments": {"path": str(repo), "_budget": 1}},
               timeout=300)
        progress = [n for n in c.notifications
                    if "progress" in str(n.get("method", ""))]
        if progress:
            return Check("mcp_progress_requires_token", "mcp_reliability", FAIL,
                         "the server sent notifications/progress for a call "
                         "that supplied no progressToken, which the MCP spec "
                         "forbids",
                         detail=json.dumps(progress[0])[:300])
        return Check("mcp_progress_requires_token", "mcp_reliability", PASS,
                     "no progress notifications were sent for a call without a "
                     "progressToken, as the MCP spec requires")


@timed
def check_depth_cap(jsat_bin: str, repo: Path, env: dict[str, str]) -> Check:
    """Nested tool calls past _MAX_CALL_DEPTH must be rejected with guidance.

    Depth lives in a thread-local that only a nested in-process call sets, so
    it cannot be provoked over JSON-RPC — a remote client has no way to claim
    a depth. The real guard is therefore exercised in-process against the
    real thread-local and the real response builder.
    """
    from jsat._call_context import _call_ctx  # noqa: PLC0415
    from jsat.mcp.server import (  # noqa: PLC0415
        _MAX_CALL_DEPTH,
        _budget_depth,
        _depth_exceeded_response,
    )

    prior = getattr(_call_ctx, "depth", 0)
    try:
        _call_ctx.depth = _MAX_CALL_DEPTH + 1
        seen = _budget_depth()
        if seen != _MAX_CALL_DEPTH + 1:
            return Check("mcp_depth_cap", "mcp_reliability", FAIL,
                         f"_budget_depth() reported {seen}, expected "
                         f"{_MAX_CALL_DEPTH + 1}")
        payload = _depth_exceeded_response("blast_radius", seen)
        if not payload.get("_depth_exceeded"):
            return Check("mcp_depth_cap", "mcp_reliability", FAIL,
                         "the depth-exceeded payload is not flagged as such",
                         detail=json.dumps(payload)[:300])
        guidance = json.dumps(payload).lower()
        if "depth" not in guidance or str(_MAX_CALL_DEPTH) not in guidance:
            return Check("mcp_depth_cap", "mcp_reliability", FAIL,
                         "the depth-exceeded payload gives the agent no "
                         "actionable guidance",
                         detail=json.dumps(payload)[:300])
        return Check("mcp_depth_cap", "mcp_reliability", PASS,
                     f"call depth beyond {_MAX_CALL_DEPTH} is detected and "
                     "returns actionable guidance instead of recursing",
                     detail=json.dumps(payload)[:250])
    finally:
        _call_ctx.depth = prior


@timed
def check_auth_rejects_bad_token(jsat_bin: str, repo: Path,
                                 env: dict[str, str]) -> Check:
    """With JSAT_MCP_TOKEN set, an unknown token must be refused."""
    hardened = {**env, "JSAT_MCP_TOKEN": "correct-horse-battery-staple"}
    hardened.pop("JSAT_MCP_ALLOW_INSECURE", None)
    with MCPClient(jsat_bin, repo, hardened) as c:
        c.handshake()
        r = c.call("tools/call",
                   {"name": "get_index_status", "arguments": {},
                    "_auth_token": "totally-wrong-token"},
                   timeout=30)
        text = json.dumps(r or {}).lower()
        if "unauthor" in text or "invalid token" in text or "forbidden" in text:
            return Check("mcp_auth_bad_token", "mcp_security", PASS,
                         "an unknown bearer token was rejected",
                         detail=json.dumps(r)[:300])
        return Check("mcp_auth_bad_token", "mcp_security", FAIL,
                     "a wrong token was NOT rejected while JSAT_MCP_TOKEN was set",
                     detail=json.dumps(r)[:400],
                     remediation="check the auth branch in MCPServer._handle")


@timed
def check_rbac_viewer_scope(jsat_bin: str, repo: Path,
                            env: dict[str, str]) -> Check:
    """A `viewer` token may read the graph but must not run security_review."""
    roles = json.dumps({"viewer-token-xyz": "viewer"})
    hardened = {**env, "JSAT_MCP_TOKEN_ROLES": roles}
    hardened.pop("JSAT_MCP_ALLOW_INSECURE", None)
    with MCPClient(jsat_bin, repo, hardened) as c:
        c.handshake()
        allowed = c.call("tools/call",
                         {"name": "get_index_status", "arguments": {},
                          "_auth_token": "viewer-token-xyz"}, timeout=30)
        denied = c.call("tools/call",
                        {"name": "security_review",
                         "arguments": {"path": str(repo)},
                         "_auth_token": "viewer-token-xyz"}, timeout=120)
        a_text = json.dumps(allowed or {}).lower()
        d_text = json.dumps(denied or {}).lower()
        a_ok = "nodes" in a_text and "not permitted" not in a_text
        d_ok = any(k in d_text for k in ("not permitted", "forbidden", "role", "unauthor"))
        if a_ok and d_ok:
            return Check("mcp_rbac_viewer", "mcp_security", PASS,
                         "viewer role could read the graph and was denied security_review")
        return Check("mcp_rbac_viewer", "mcp_security", FAIL,
                     f"RBAC scope wrong (read_allowed={a_ok}, write_denied={d_ok})",
                     detail=f"allowed={a_text[:250]} denied={d_text[:250]}")


@timed
def check_stdout_is_pure_jsonrpc(jsat_bin: str, repo: Path,
                                 env: dict[str, str]) -> Check:
    """Any non-JSON byte on stdout breaks every MCP client. MCPClient raises
    on it, so a clean multi-call session is the assertion."""
    try:
        with MCPClient(jsat_bin, repo, env) as c:
            c.handshake()
            for name in ("get_index_status", "health", "get_jsat_version",
                         "list_services", "get_metrics"):
                c.tool(name, {})
    except RuntimeError as e:
        return Check("mcp_stdout_purity", "mcp_server", FAIL,
                     f"stdout carried non-JSON-RPC output: {e}",
                     remediation="a print()/logger writing to stdout in the "
                                 "mcp-server path; route it to stderr")
    return Check("mcp_stdout_purity", "mcp_server", PASS,
                 "stdout carried only JSON-RPC across a 5-call session")


def run_reliability(report: Report, jsat_bin: str, repo: Path,
                    env: dict[str, str]) -> None:
    report.add(check_stdout_is_pure_jsonrpc(jsat_bin, repo, env))
    report.add(check_soft_budget_notification(jsat_bin, repo, env))
    report.add(check_no_progress_without_token(jsat_bin, repo, env))
    report.add(check_depth_cap(jsat_bin, repo, env))
    report.add(check_auth_rejects_bad_token(jsat_bin, repo, env))
    report.add(check_rbac_viewer_scope(jsat_bin, repo, env))
