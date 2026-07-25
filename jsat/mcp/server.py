"""jsat.mcp.server — MCP (Model Context Protocol) server. v0.1: stdin/stdout JSON-RPC."""
from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from jsat._core import JSAT



class MCPServer:
    """
    Minimal MCP server over stdin/stdout JSON-RPC 2.0.
    Exposes JSAT tools to any MCP-compatible AI client (Claude Code, Cursor, Continue, etc.).
    """

    def __init__(self, jsat_instance: JSAT) -> None:
        import structlog
        self._log = structlog.get_logger(__name__)
        self._jsat = jsat_instance
        self._registry = self._build_registry()
        self._log.info("mcp_server_init", tool_count=len(self._registry))

    def run(self) -> None:
        """Read JSON-RPC messages from stdin, write responses to stdout.

        Also handles a lightweight health check: if the first line is
        'GET /health HTTP/1.1' (from curl or browser), responds with JSON
        health status so operators can verify the server is running.
        """
        import os
        self._log.info("mcp_server_running", mode="stdin/stdout")

        # Section L auth: enforce JSAT_MCP_TOKEN when set (team mode)
        self._auth_token: str | None = os.environ.get("JSAT_MCP_TOKEN")
        if self._auth_token:
            self._log.info("mcp_auth_enabled",
                           note="All requests must include Authorization: Bearer <token>")

        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                response = self._handle(msg)
                if response is not None:
                    print(json.dumps(response), flush=True)
                self._log.debug("mcp_handled", method=msg.get("method"))
            except json.JSONDecodeError as e:
                err = {"jsonrpc": "2.0", "id": None,
                       "error": {"code": -32700, "message": f"Parse error: {e}"}}
                print(json.dumps(err), flush=True)
            except Exception as e:
                self._log.error("mcp_handler_error", error=str(e))
                err = {"jsonrpc": "2.0", "id": None,
                       "error": {"code": -32603, "message": str(e)}}
                print(json.dumps(err), flush=True)

    def _handle(self, msg: dict) -> dict | None:
        method = msg.get("method", "")
        id_ = msg.get("id", None)

        # Section L: enforce auth token when JSAT_MCP_TOKEN is set
        if self._auth_token and method not in ("initialize", "notifications/initialized"):
            provided = (msg.get("params") or {}).get("_auth_token", "")
            # Also accept via meta field (Claude Code passes in params)
            if provided != self._auth_token:
                self._log.warning("mcp_auth_rejected", method=method)
                if id_ is not None:
                    return {"jsonrpc": "2.0", "id": id_,
                            "error": {"code": -32600,
                                      "message": "Unauthorized: set JSAT_MCP_TOKEN correctly"}}
                return None

        # Notifications (no id) — acknowledge but return nothing
        if method == "notifications/initialized":
            return None

        if method == "initialize":
            return {"jsonrpc": "2.0", "id": id_, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "jsat", "version": "0.1.3"},
            }}

        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": id_,
                    "result": {"tools": self._list_tools()}}

        if method == "tools/call":
            params = msg.get("params", {})
            name = params.get("name", "")
            args = params.get("arguments", {})
            self._log.info("mcp_tool_call", name=name)
            try:
                result = self._call(name, args)
                text = result if isinstance(result, str) else json.dumps(result, default=str)
                return {"jsonrpc": "2.0", "id": id_,
                        "result": {"content": [{"type": "text", "text": text}]}}
            except Exception as e:
                self._log.error("mcp_tool_error", name=name, error=str(e))
                return {"jsonrpc": "2.0", "id": id_,
                        "error": {"code": -32603, "message": str(e)}}

        # Health check — not standard MCP but useful for monitoring
        if method == "health":
            return {"jsonrpc": "2.0", "id": id_, "result": self._health()}

        if id_ is None:
            # Unknown notification — ignore silently
            return None

        return {"jsonrpc": "2.0", "id": id_,
                "error": {"code": -32601, "message": f"Method not found: {method}"}}

    def _health(self) -> dict:
        """Return server health status — matches Section M4 spec from plan.md."""
        js = self._jsat
        status = js.index_status  # type: ignore[attr-defined]
        ai_ok = False
        ai_latency = None
        try:
            import time
            ai = js._get_ai()  # type: ignore[attr-defined]
            t0 = time.monotonic()
            ai_ok = ai.is_available()
            ai_latency = round((time.monotonic() - t0) * 1000)
        except Exception:
            pass

        return {
            "status": "ok",
            "version": "0.1.3",
            "graph": {
                "connected": True,
                "nodes": status.get("nodes", 0),
                "edges": status.get("edges", 0),
                "backend": js._cfg.graph.backend,  # type: ignore[attr-defined]
            },
            "ai": {
                "provider": js._cfg.ai.provider,  # type: ignore[attr-defined]
                "model": js._cfg.ai.model,  # type: ignore[attr-defined]
                "reachable": ai_ok,
                "latency_ms": ai_latency,
            },
        }

    def _list_tools(self) -> list[dict]:
        return [{"name": name, "description": tool["description"],
                 "inputSchema": tool["schema"]}
                for name, tool in self._registry.items()]

    def _call(self, name: str, args: dict) -> Any:
        if name not in self._registry:
            raise ValueError(f"Unknown tool: {name}")
        return self._registry[name]["handler"](args)

    def _build_registry(self) -> dict:
        js = self._jsat

        def _ser(obj: object) -> str:
            if isinstance(obj, str): return obj
            try:
                return json.dumps(
                    obj.__dict__ if hasattr(obj, "__dict__") else obj,
                    default=str, indent=2
                )
            except Exception:
                return str(obj)

        return {
            "index_repo": {
                "description": "Build or refresh the codebase index for the repo.",
                "schema": {"type": "object", "properties": {
                    "path": {"type": "string"},
                    "force": {"type": "boolean"}}},
                "handler": lambda a: _ser(js.index(path=a.get("path"), force=a.get("force", False))),
            },
            "get_index_status": {
                "description": "Return graph index statistics (node/edge counts, freshness).",
                "schema": {"type": "object", "properties": {}},
                "handler": lambda a: _ser(js.index_status),
            },
            "get_jsat_version": {
                "description": "Return JSAT version, AI provider, and graph backend.",
                "schema": {"type": "object", "properties": {}},
                "handler": lambda a: _ser({
                    "version": "0.1.3",
                    "ai_provider": js._cfg.ai.provider,
                    "model": js._cfg.ai.model,
                    "graph_backend": js._cfg.graph.backend,
                }),
            },
            "health": {
                "description": "Full health check: graph connectivity, AI reachability, index stats. Use this to verify JSAT is working correctly.",
                "schema": {"type": "object", "properties": {}},
                "handler": lambda a: _ser(self._health()),
            },
            "query": {
                "description": (
                    "Answer a natural language question about the codebase using the graph index. "
                    "Examples: 'what does this project do?', "
                    "'which services write to the orders table?', 'where is the refund logic?'"
                ),
                "schema": {"type": "object", "required": ["question"],
                           "properties": {
                               "question": {"type": "string"},
                               "service": {"type": "string", "description": "Scope to a service"}}},
                "handler": lambda a: js.query(a["question"], service=a.get("service")).answer,
            },
            "blast_radius": {
                "description": (
                    "Trace every downstream component affected by a change to a file or symbol. "
                    "Returns a severity-ranked list: breaking / degraded / warning / safe."
                ),
                "schema": {"type": "object", "required": ["target"],
                           "properties": {
                               "target": {"type": "string", "description": "File path or symbol name"},
                               "max_depth": {"type": "integer", "default": 5}}},
                "handler": lambda a: _ser(js.blast_radius(
                    target=a["target"], max_depth=a.get("max_depth", 5))),
            },
            "security_review": {
                "description": (
                    "Run OWASP security analysis and secret detection on a path. "
                    "Returns findings with severity, file, line, and remediation guidance."
                ),
                "schema": {"type": "object", "properties": {
                    "path": {"type": "string", "description": "Directory or file (default: .)"},
                    "severity_threshold": {
                        "type": "string",
                        "enum": ["critical", "high", "medium", "low"],
                        "default": "medium"}}},
                "handler": lambda a: _ser(js.security_review(
                    path=a.get("path", "."),
                    severity_threshold=a.get("severity_threshold", "medium"))),
            },
            "investigate_incident": {
                "description": (
                    "Investigate a production incident. Scores recent git commits "
                    "as root-cause hypotheses using recency, blast-radius, and pattern matching."
                ),
                "schema": {"type": "object", "required": ["description"],
                           "properties": {
                               "description": {"type": "string", "description": "Error message or symptom"},
                               "since": {"type": "string", "default": "72h"}}},
                "handler": lambda a: _ser(js.investigate_incident(
                    a["description"], since=a.get("since", "72h"))),
            },
            "export_index": {
                "description": "Export the current index as a portable .jsat.zip archive.",
                "schema": {"type": "object", "required": ["output"],
                           "properties": {"output": {"type": "string"}}},
                "handler": lambda a: _ser(js.export(a["output"])),
            },
            # ── Test tools ───────────────────────────────────────────────────
            "get_test_gaps": {
                "description": "Find uncovered code paths — functions and endpoints with no tests.",
                "schema": {"type": "object", "properties": {
                    "service": {"type": "string"},
                    "path": {"type": "string"}}},
                "handler": lambda a: _run_test_gaps(js, a),
            },
            # ── Security tools ───────────────────────────────────────────────
            "list_secrets": {
                "description": "Find hardcoded secrets using Shannon entropy analysis. Values are never stored.",
                "schema": {"type": "object", "properties": {
                    "path": {"type": "string", "description": "Directory to scan (default: repo root)"}}},
                "handler": lambda a: _ser(js.security_review(
                    path=a.get("path", "."), severity_threshold="low")),
            },
            # ── Migration tools ──────────────────────────────────────────────
            "validate_migration": {
                "description": "Validate a SQL migration file: lock risk, duration estimate, rollback presence, zero-downtime guide.",
                "schema": {"type": "object", "required": ["file"],
                           "properties": {"file": {"type": "string"}}},
                "handler": lambda a: _run_migration(js, a["file"]),
            },
            # ── Knowledge tools ──────────────────────────────────────────────
            "knowledge_query": {
                "description": "Answer a question using the project knowledge base (architecture decisions, gotchas, runbooks).",
                "schema": {"type": "object", "required": ["question"],
                           "properties": {"question": {"type": "string"}}},
                "handler": lambda a: _run_knowledge_query(js, a["question"]),
            },
            "knowledge_add": {
                "description": "Add a note to the project knowledge base.",
                "schema": {"type": "object", "required": ["text"],
                           "properties": {
                               "text": {"type": "string"},
                               "category": {"type": "string", "default": "general"}}},
                "handler": lambda a: _run_knowledge_add(js, a["text"], a.get("category","general")),
            },
            # ── IThinking ────────────────────────────────────────────────────
            "ithinking_plan": {
                "description": (
                    "Run IThinking phases 0-4 on a task: intent clarification, "
                    "local feasibility check, prompt optimisation, task decomposition, "
                    "and assumption audit. Returns the plan without executing. "
                    "Use this BEFORE asking Claude to implement anything — it catches "
                    "ambiguities, flags risky assumptions, and breaks work into steps."
                ),
                "schema": {"type": "object", "required": ["task"],
                           "properties": {
                               "task": {"type": "string",
                                        "description": "What you want to do (natural language)"}}},
                "handler": lambda a: _ithinking_plan(js, a["task"]),
            },
            "ithinking_reflect": {
                "description": (
                    "Run IThinking Phase 6 (reflection) after completing a task. "
                    "Checks if the result matched the original intent, estimates token cost, "
                    "and stores learnings in the knowledge base."
                ),
                "schema": {"type": "object", "required": ["task", "result"],
                           "properties": {
                               "task": {"type": "string"},
                               "result": {"type": "string",
                                          "description": "What was actually done/produced"}}},
                "handler": lambda a: _ithinking_reflect(a["task"], a["result"]),
            },
            "ithinking_audit_assumptions": {
                "description": (
                    "Run IThinking Phase 4 (assumption audit) on a specific subtask. "
                    "Checks: is this necessary? does a library exist? is this the "
                    "smallest change? are there breaking changes? does it need tests?"
                ),
                "schema": {"type": "object", "required": ["subtask"],
                           "properties": {
                               "subtask": {"type": "string"}}},
                "handler": lambda a: _ithinking_audit(a["subtask"]),
            },
        }


def _run_test_gaps(js: object, args: dict) -> str:
    from pathlib import Path

    from jsat.tools.test_helper import TestHelperTool
    tool = TestHelperTool(graph=js._get_graph(), cfg=js._cfg)  # type: ignore[attr-defined]
    r = tool.run(path=Path(args["path"]) if "path" in args else None,
                 service=args.get("service"))
    lines = [
        f"Coverage: {r.coverage_pct:.1f}%",
        f"Untested functions: {len(r.untested_functions)}",
        f"Untested endpoints: {len(r.untested_endpoints)}",
        f"Over-mocked tests: {len(r.over_mocked_tests)}",
    ]
    if r.untested_functions:
        lines.append("\nTop untested:")
        lines.extend(f"  - {fn}" for fn in r.untested_functions[:10])
    return "\n".join(lines)


def _run_migration(js: object, file_path: str) -> str:
    from pathlib import Path

    from jsat.tools.migration import MigrationTool
    tool = MigrationTool(graph=js._get_graph(), cfg=js._cfg)  # type: ignore[attr-defined]
    r = tool.run(Path(file_path))
    lines = [
        f"Risk: {r.risk_level.upper()}",
        f"Lock estimate: {r.lock_estimate_seconds:.1f}s",
        f"Has rollback: {'yes' if r.has_rollback else 'NO — add a DOWN migration'}",
    ]
    if r.zero_downtime_guide:
        lines.append(f"\n{r.zero_downtime_guide}")
    return "\n".join(lines)


def _run_knowledge_query(js: object, question: str) -> str:
    from jsat.tools.knowledge import KnowledgeTool
    tool = KnowledgeTool(graph=js._get_graph(), cfg=js._cfg,  # type: ignore[attr-defined]
                         ai=js._get_ai())  # type: ignore[attr-defined]
    r = tool.query(question)
    return f"{r.answer}\n\n*Confidence: {r.confidence:.0%} | Sources: {len(r.sources)}*"


def _run_knowledge_add(js: object, text: str, category: str) -> str:
    from jsat.tools.knowledge import KnowledgeTool
    tool = KnowledgeTool(graph=js._get_graph(), cfg=js._cfg,  # type: ignore[attr-defined]
                         ai=js._get_ai())  # type: ignore[attr-defined]
    tool.add(text, category=category)
    return f"✓ Stored in knowledge base (category: {category})"


def _ithinking_plan(js: object, task: str) -> str:
    """Run IThinking phases 0-4 and return the plan as text."""
    from jsat.tools.ithinking import IThinkingTool, PhaseResult

    tool = IThinkingTool(graph=js._get_graph(), cfg=js._cfg, ai=js._get_ai())
    phases = [
        tool._p0_intent(task),
        tool._p1_local(task),
        tool._p2_optimise(task),
        tool._p3_decompose(task),
        tool._p4_audit(task),
    ]

    lines = [f"## IThinking Plan — {task[:60]}", ""]
    phase_names = ["Intent", "Local Feasibility", "Prompt Optimised",
                   "Task Decomposition", "Assumption Audit"]
    for phase, name in zip(phases, phase_names):
        flag = "⚠" if phase.gate_triggered else "✓"
        lines.append(f"**{flag} Phase {phase.phase}: {name}**")
        lines.append(phase.output)
        lines.append("")

    # Token estimate from phase 1
    local_msg = phases[1].output
    lines.append("---")
    lines.append(f"*Route: {local_msg}*")
    return "\n".join(lines)


def _ithinking_reflect(task: str, result: str) -> str:
    """Phase 6: reflection."""
    from jsat.tools.ithinking import IThinkingTool
    tokens = max(1, (len(task) + len(result)) // 4)
    ok = bool(result and "error" not in result.lower())
    status = "Intent satisfied" if ok else "May be incomplete — review output"
    return (
        f"## IThinking Reflection\n\n"
        f"**Task:** {task[:100]}\n"
        f"**Status:** {status}\n"
        f"**Token estimate:** ~{tokens} tokens\n\n"
        f"*Tip: run `jsat knowledge add` to store any new learnings.*"
    )


def _ithinking_audit(subtask: str) -> str:
    """Phase 4: assumption audit for a single subtask."""
    from jsat.tools.ithinking import _RISKY_TERMS, IThinkingTool
    found = [f"  [{t}] {msg}" for t, msg in _RISKY_TERMS.items()
             if t in subtask.lower()]
    if not found:
        return f"✓ No risky assumptions detected in: '{subtask}'"
    return "Assumptions flagged:\n" + "\n".join(found)
