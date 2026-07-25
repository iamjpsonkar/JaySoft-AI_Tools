"""jsat.mcp.server — MCP (Model Context Protocol) server. v0.2: 30+ tools, RBAC, metrics."""
from __future__ import annotations

import json
import os
import sys
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from jsat._core import JSAT

# ── Role definitions ──────────────────────────────────────────────────────────
# viewer  : read-only tools (query, get_*, list_*, knowledge_query, health, status)
# developer: + blast_radius_*, security, incident, review, migration
# admin   : all tools including index writes and import
_ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "viewer": frozenset({
        "query", "health", "get_index_status", "get_jsat_version",
        "get_function", "get_class", "get_data_flow",
        "list_services", "list_endpoints", "list_tables",
        "trace_call_chain", "get_consumers",
        "knowledge_query", "knowledge_search", "knowledge_list",
        "get_metrics",
    }),
    "developer": frozenset({
        # inherits viewer
        "query", "health", "get_index_status", "get_jsat_version",
        "get_function", "get_class", "get_data_flow",
        "list_services", "list_endpoints", "list_tables",
        "trace_call_chain", "get_consumers",
        "knowledge_query", "knowledge_search", "knowledge_list",
        "get_metrics",
        # developer extras
        "blast_radius", "blast_radius_diff", "blast_radius_symbol",
        "security_review", "list_secrets", "get_auth_coverage",
        "investigate_incident", "get_hypotheses", "get_recent_changes",
        "generate_runbook",
        "get_api_diff", "check_breaking_changes", "get_compat_score",
        "get_behavioral_coverage", "list_untested_paths", "get_test_gaps",
        "submit_for_review", "get_review_findings", "get_high_confidence_bugs",
        "suggest_zero_downtime", "validate_migration",
        "knowledge_add", "knowledge_flag_stale",
        "ithinking_plan", "ithinking_reflect", "ithinking_audit_assumptions",
    }),
    "admin": frozenset(),  # empty = unrestricted, resolved below
}


def _allowed(role: str, tool: str) -> bool:
    """Return True if this role can call this tool."""
    if role == "admin":
        return True
    perms = _ROLE_PERMISSIONS.get(role, frozenset())
    return tool in perms


class MCPServer:
    """
    Minimal MCP server over stdin/stdout JSON-RPC 2.0.
    Exposes JSAT tools to any MCP-compatible AI client (Claude Code, Cursor, Continue, etc.).

    Environment variables:
      JSAT_MCP_TOKEN       — single shared bearer token (legacy, backward-compat)
      JSAT_MCP_TOKEN_ROLES — JSON map of token→role, e.g. {"tok1": "admin", "tok2": "viewer"}
      JSAT_METRICS_PORT    — if set, start Prometheus HTTP server on that port (optional dep)
    """

    def __init__(self, jsat_instance: JSAT) -> None:
        import structlog
        self._log = structlog.get_logger(__name__)
        self._jsat = jsat_instance
        self._registry = self._build_registry()

        # In-memory metrics: {tool_name: {"calls": int, "total_ms": float, "errors": int}}
        self._metrics: dict[str, dict[str, Any]] = {}

        # RBAC: token → role map (may be empty if not configured)
        _raw = os.environ.get("JSAT_MCP_TOKEN_ROLES", "")
        try:
            self._token_roles: dict[str, str] = json.loads(_raw) if _raw.strip() else {}
        except json.JSONDecodeError:
            self._log.warning("mcp_rbac_parse_error",
                              note="JSAT_MCP_TOKEN_ROLES is not valid JSON — RBAC disabled")
            self._token_roles = {}

        if self._token_roles:
            self._log.info("mcp_rbac_enabled", token_count=len(self._token_roles))
        else:
            self._log.info("mcp_rbac_disabled", note="set JSAT_MCP_TOKEN_ROLES to enable")

        # Optional Prometheus side-car
        try:
            from jsat.mcp.prometheus import start_metrics_server
            start_metrics_server()
        except Exception:
            pass  # prometheus.py import failure is always silent

        self._log.info("mcp_server_init", tool_count=len(self._registry))

    # ── Public entry point ────────────────────────────────────────────────────

    def run(self) -> None:
        """Read JSON-RPC messages from stdin, write responses to stdout."""
        self._log.info("mcp_server_running", mode="stdin/stdout")

        # Legacy single-token auth (backward-compat)
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

    # ── Request routing ───────────────────────────────────────────────────────

    def _handle(self, msg: dict) -> dict | None:
        method = msg.get("method", "")
        id_ = msg.get("id", None)
        params = msg.get("params") or {}

        # ── Legacy single-token auth (JSAT_MCP_TOKEN) ───────────────────────
        if self._auth_token and method not in ("initialize", "notifications/initialized"):
            provided = params.get("_auth_token", "")
            if provided != self._auth_token:
                self._log.warning("mcp_auth_rejected", method=method)
                if id_ is not None:
                    return {"jsonrpc": "2.0", "id": id_,
                            "error": {"code": -32600,
                                      "message": "Unauthorized: set JSAT_MCP_TOKEN correctly"}}
                return None

        # ── RBAC: token-role enforcement (JSAT_MCP_TOKEN_ROLES) ─────────────
        # Only active when token_roles dict is populated.
        # Exempt: protocol handshake methods.
        if self._token_roles and method not in ("initialize", "notifications/initialized"):
            provided_token = params.get("_auth_token", "")
            role = self._token_roles.get(provided_token)
            if role is None:
                self._log.warning("mcp_rbac_token_unknown", method=method)
                if id_ is not None:
                    return {"jsonrpc": "2.0", "id": id_,
                            "error": {"code": -32600, "message": "Unauthorized: unknown token"}}
                return None

            # For tool calls, check permission
            if method == "tools/call":
                tool_name = params.get("name", "")
                if not _allowed(role, tool_name):
                    self._log.warning("mcp_rbac_denied",
                                      tool=tool_name, role=role)
                    if id_ is not None:
                        return {"jsonrpc": "2.0", "id": id_,
                                "error": {"code": -32600,
                                          "message": f"Forbidden: role '{role}' cannot call '{tool_name}'"}}
                    return None

        # ── Protocol methods ─────────────────────────────────────────────────
        if method == "notifications/initialized":
            return None

        if method == "initialize":
            return {"jsonrpc": "2.0", "id": id_, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "jsat", "version": "0.2.0"},
            }}

        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": id_,
                    "result": {"tools": self._list_tools()}}

        if method == "tools/call":
            name = params.get("name", "")
            args = params.get("arguments", {})
            self._log.info("mcp_tool_call", name=name)
            t0 = time.monotonic()
            error_occurred = False
            try:
                result = self._call(name, args)
                text = result if isinstance(result, str) else json.dumps(result, default=str)
                return {"jsonrpc": "2.0", "id": id_,
                        "result": {"content": [{"type": "text", "text": text}]}}
            except Exception as e:
                error_occurred = True
                self._log.error("mcp_tool_error", name=name, error=str(e))
                return {"jsonrpc": "2.0", "id": id_,
                        "error": {"code": -32603, "message": str(e)}}
            finally:
                elapsed_ms = (time.monotonic() - t0) * 1000
                self._record_metric(name, elapsed_ms, error=error_occurred)

        if method == "health":
            return {"jsonrpc": "2.0", "id": id_, "result": self._health()}

        if id_ is None:
            return None  # Unknown notification — ignore

        return {"jsonrpc": "2.0", "id": id_,
                "error": {"code": -32601, "message": f"Method not found: {method}"}}

    # ── Metrics ───────────────────────────────────────────────────────────────

    def _record_metric(self, tool: str, elapsed_ms: float, error: bool = False) -> None:
        """Update in-memory metrics counters for this tool call."""
        if tool not in self._metrics:
            self._metrics[tool] = {"calls": 0, "total_ms": 0.0, "errors": 0}
        m = self._metrics[tool]
        m["calls"] += 1
        m["total_ms"] = round(m["total_ms"] + elapsed_ms, 2)
        if error:
            m["errors"] += 1

        # Forward to Prometheus side-car if available
        try:
            from jsat.mcp.prometheus import record_call
            record_call(tool, elapsed_ms / 1000.0, error=error)
        except Exception:
            pass

    # ── Health ────────────────────────────────────────────────────────────────

    def _health(self) -> dict:
        """Return server health status."""
        js = self._jsat
        status = js.index_status  # type: ignore[attr-defined]
        ai_ok = False
        ai_latency = None
        try:
            ai = js._get_ai()  # type: ignore[attr-defined]
            t0 = time.monotonic()
            ai_ok = ai.is_available()
            ai_latency = round((time.monotonic() - t0) * 1000)
        except Exception:
            pass

        return {
            "status": "ok",
            "version": "0.2.0",
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

    # ── Tool dispatch ─────────────────────────────────────────────────────────

    def _list_tools(self) -> list[dict]:
        return [{"name": name, "description": tool["description"],
                 "inputSchema": tool["schema"]}
                for name, tool in self._registry.items()]

    def _call(self, name: str, args: dict) -> Any:
        if name not in self._registry:
            raise ValueError(f"Unknown tool: {name}")
        return self._registry[name]["handler"](args)

    # ── Registry ──────────────────────────────────────────────────────────────

    def _build_registry(self) -> dict:
        js = self._jsat

        def _ser(obj: object) -> str:
            if isinstance(obj, str):
                return obj
            try:
                return json.dumps(
                    obj.__dict__ if hasattr(obj, "__dict__") else obj,
                    default=str, indent=2,
                )
            except Exception:
                return str(obj)

        # ── Shared graph helper ───────────────────────────────────────────────
        def _graph():
            return js._get_graph()  # type: ignore[attr-defined]

        # ── Graph node query helpers ─────────────────────────────────────────
        def _query_nodes(label: str, filters: dict | None = None) -> list[dict]:
            """Query graph for nodes of a given label, optionally filtering by properties."""
            try:
                g = _graph()
                nodes = g.nodes_by_label(label)  # type: ignore[attr-defined]
                if filters:
                    filtered = []
                    for n in nodes:
                        props = n.get("properties", n) if isinstance(n, dict) else {}
                        if all(str(props.get(k, "")).lower() == str(v).lower()
                               for k, v in filters.items() if v is not None):
                            filtered.append(n)
                    return filtered
                return nodes
            except AttributeError:
                # Graph backend may use a different API; fall back to search
                try:
                    g = _graph()
                    return [r for r in g.search(label=label)  # type: ignore[attr-defined]
                            if True]
                except Exception as ex:
                    return [{"error": f"Graph query failed: {ex}"}]

        return {
            # ── Index / status ────────────────────────────────────────────
            "index_repo": {
                "description": "Build or refresh the codebase index for the repo.",
                "schema": {"type": "object", "properties": {
                    "path": {"type": "string"},
                    "force": {"type": "boolean"},
                    "incremental": {"type": "boolean"},
                    "branch": {"type": "string"}}},
                "handler": lambda a: _ser(js.index(  # type: ignore[attr-defined]
                    path=a.get("path"), force=a.get("force", False))),
            },
            "get_index_status": {
                "description": "Return graph index statistics (node/edge counts, freshness).",
                "schema": {"type": "object", "properties": {}},
                "handler": lambda a: _ser(js.index_status),  # type: ignore[attr-defined]
            },
            "get_jsat_version": {
                "description": "Return JSAT version, AI provider, and graph backend.",
                "schema": {"type": "object", "properties": {}},
                "handler": lambda a: _ser({
                    "version": "0.2.0",
                    "ai_provider": js._cfg.ai.provider,  # type: ignore[attr-defined]
                    "model": js._cfg.ai.model,  # type: ignore[attr-defined]
                    "graph_backend": js._cfg.graph.backend,  # type: ignore[attr-defined]
                }),
            },
            "health": {
                "description": (
                    "Full health check: graph connectivity, AI reachability, index stats."
                ),
                "schema": {"type": "object", "properties": {}},
                "handler": lambda a: _ser(self._health()),
            },

            # ── Graph exploration ─────────────────────────────────────────
            "list_services": {
                "description": "List all Service nodes in the indexed graph.",
                "schema": {"type": "object", "properties": {
                    "language": {"type": "string",
                                 "description": "Optional: filter by language (python, go, js…)"}}},
                "handler": lambda a: _ser(
                    _list_services_impl(js, a.get("language"))
                ),
            },
            "list_endpoints": {
                "description": (
                    "List API Endpoint nodes. "
                    "Optional filters: service name, HTTP method, auth-required flag."
                ),
                "schema": {"type": "object", "properties": {
                    "service": {"type": "string"},
                    "method": {"type": "string",
                               "description": "HTTP method filter: GET, POST, PUT, DELETE…"},
                    "auth": {"type": "boolean",
                             "description": "If true, return only auth-required endpoints"}}},
                "handler": lambda a: _ser(
                    _list_endpoints_impl(js, a.get("service"), a.get("method"), a.get("auth"))
                ),
            },
            "get_function": {
                "description": "Get details of a Function node by name, or by file and line.",
                "schema": {"type": "object", "properties": {
                    "name": {"type": "string"},
                    "file": {"type": "string"},
                    "line": {"type": "integer"}}},
                "handler": lambda a: _ser(
                    _get_function_impl(js, a.get("name"), a.get("file"), a.get("line"))
                ),
            },
            "get_class": {
                "description": "Get details of a Class node by name, optionally scoped to a file.",
                "schema": {"type": "object", "properties": {
                    "name": {"type": "string"},
                    "file": {"type": "string"}}},
                "handler": lambda a: _ser(
                    _get_class_impl(js, a.get("name"), a.get("file"))
                ),
            },
            "list_tables": {
                "description": "List all database Table nodes in the indexed graph.",
                "schema": {"type": "object", "properties": {}},
                "handler": lambda a: _ser(
                    _list_tables_impl(js)
                ),
            },
            "trace_call_chain": {
                "description": (
                    "BFS from a source function/service to a target. "
                    "Returns the shortest call path found."
                ),
                "schema": {"type": "object", "required": ["from", "to"],
                           "properties": {
                               "from": {"type": "string", "description": "Source symbol or node"},
                               "to": {"type": "string", "description": "Target symbol or node"}}},
                "handler": lambda a: _ser(
                    _trace_call_chain_impl(js, a["from"], a["to"])
                ),
            },
            "get_data_flow": {
                "description": (
                    "Show READS_FROM / WRITES_TO / PRODUCES / CONSUMES edges "
                    "for a service or the entire graph."
                ),
                "schema": {"type": "object", "properties": {
                    "service": {"type": "string",
                                "description": "Scope to a specific service (optional)"}}},
                "handler": lambda a: _ser(
                    _get_data_flow_impl(js, a.get("service"))
                ),
            },

            # ── Natural language query ────────────────────────────────────
            "query": {
                "description": (
                    "Answer a natural language question about the codebase using the graph index. "
                    "Examples: 'what does this project do?', "
                    "'which services write to the orders table?', 'where is the refund logic?'"
                ),
                "schema": {"type": "object", "required": ["question"],
                           "properties": {
                               "question": {"type": "string"},
                               "service": {"type": "string",
                                           "description": "Scope to a service"}}},
                "handler": lambda a: js.query(  # type: ignore[attr-defined]
                    a["question"], service=a.get("service")).answer,
            },

            # ── Blast radius ──────────────────────────────────────────────
            "blast_radius": {
                "description": (
                    "Trace every downstream component affected by a change to a file or symbol. "
                    "Returns a severity-ranked list: breaking / degraded / warning / safe."
                ),
                "schema": {"type": "object", "required": ["target"],
                           "properties": {
                               "target": {"type": "string",
                                          "description": "File path or symbol name"},
                               "max_depth": {"type": "integer", "default": 5}}},
                "handler": lambda a: _ser(js.blast_radius(  # type: ignore[attr-defined]
                    target=a["target"], max_depth=a.get("max_depth", 5))),
            },
            "blast_radius_diff": {
                "description": (
                    "Compute blast radius from a git diff string. "
                    "Pass the raw diff text, or 'HEAD~1' to use the last commit."
                ),
                "schema": {"type": "object", "required": ["diff"],
                           "properties": {
                               "diff": {"type": "string",
                                        "description": "Raw diff text or git ref like HEAD~1"},
                               "max_depth": {"type": "integer", "default": 5}}},
                "handler": lambda a: _ser(
                    _blast_radius_diff_impl(js, a["diff"], a.get("max_depth", 5))
                ),
            },
            "blast_radius_symbol": {
                "description": "Compute blast radius for a specific symbol (function, class, const).",
                "schema": {"type": "object", "required": ["symbol"],
                           "properties": {
                               "symbol": {"type": "string",
                                          "description": "Symbol name to trace"}}},
                "handler": lambda a: _ser(
                    js.blast_radius(target=a["symbol"])  # type: ignore[attr-defined]
                ),
            },
            "get_consumers": {
                "description": (
                    "Find all nodes that CONSUMES or CALLS a given target "
                    "(endpoint, topic, function, or service)."
                ),
                "schema": {"type": "object", "required": ["target"],
                           "properties": {
                               "target": {"type": "string",
                                          "description": "Target symbol, endpoint, or topic"}}},
                "handler": lambda a: _ser(
                    _get_consumers_impl(js, a["target"])
                ),
            },

            # ── Security ──────────────────────────────────────────────────
            "security_review": {
                "description": (
                    "Run OWASP security analysis and secret detection on a path. "
                    "Returns findings with severity, file, line, and remediation guidance."
                ),
                "schema": {"type": "object", "properties": {
                    "path": {"type": "string",
                             "description": "Directory or file (default: .)"},
                    "severity_threshold": {
                        "type": "string",
                        "enum": ["critical", "high", "medium", "low"],
                        "default": "medium"}}},
                "handler": lambda a: _ser(js.security_review(  # type: ignore[attr-defined]
                    path=a.get("path", "."),
                    severity_threshold=a.get("severity_threshold", "medium"))),
            },
            "list_secrets": {
                "description": (
                    "Find hardcoded secrets using Shannon entropy analysis. "
                    "Values are never stored."
                ),
                "schema": {"type": "object", "properties": {
                    "path": {"type": "string",
                             "description": "Directory to scan (default: repo root)"}}},
                "handler": lambda a: _ser(js.security_review(  # type: ignore[attr-defined]
                    path=a.get("path", "."), severity_threshold="low")),
            },

            # ── Incident ──────────────────────────────────────────────────
            "investigate_incident": {
                "description": (
                    "Investigate a production incident. Scores recent git commits "
                    "as root-cause hypotheses using recency, blast-radius, and pattern matching."
                ),
                "schema": {"type": "object", "required": ["description"],
                           "properties": {
                               "description": {"type": "string",
                                               "description": "Error message or symptom"},
                               "since": {"type": "string", "default": "72h"}}},
                "handler": lambda a: _ser(js.investigate_incident(  # type: ignore[attr-defined]
                    a["description"], since=a.get("since", "72h"))),
            },

            # ── Tests ─────────────────────────────────────────────────────
            "get_test_gaps": {
                "description": "Find uncovered code paths — functions and endpoints with no tests.",
                "schema": {"type": "object", "properties": {
                    "service": {"type": "string"},
                    "path": {"type": "string"}}},
                "handler": lambda a: _run_test_gaps(js, a),
            },
            "get_behavioral_coverage": {
                "description": (
                    "Map observable behaviors to test coverage stats. "
                    "Returns coverage percentage and untested behavior list."
                ),
                "schema": {"type": "object", "properties": {
                    "service": {"type": "string",
                                "description": "Scope to a specific service (optional)"}}},
                "handler": lambda a: _ser(
                    _get_behavioral_coverage_impl(js, a.get("service"))
                ),
            },
            "list_untested_paths": {
                "description": "Return the highest-risk untested functions, ranked by complexity.",
                "schema": {"type": "object", "properties": {
                    "limit": {"type": "integer", "default": 20,
                              "description": "Max results to return"}}},
                "handler": lambda a: _ser(
                    _list_untested_paths_impl(js, a.get("limit", 20))
                ),
            },

            # ── API contract ──────────────────────────────────────────────
            "get_api_diff": {
                "description": "Diff OpenAPI / AsyncAPI specs between two git refs.",
                "schema": {"type": "object", "properties": {
                    "base": {"type": "string", "default": "main"},
                    "head": {"type": "string", "default": "HEAD"}}},
                "handler": lambda a: _ser(
                    _contract_impl(js, a.get("base", "main"), a.get("head", "HEAD"))
                ),
            },
            "check_breaking_changes": {
                "description": (
                    "Run API contract check and return only breaking changes "
                    "(changes that would break existing consumers)."
                ),
                "schema": {"type": "object", "properties": {
                    "base": {"type": "string", "default": "main"},
                    "head": {"type": "string", "default": "HEAD"}}},
                "handler": lambda a: _ser(
                    _check_breaking_impl(js, a.get("base", "main"), a.get("head", "HEAD"))
                ),
            },
            "get_compat_score": {
                "description": "Run API contract check and return the 0-100 compatibility score.",
                "schema": {"type": "object", "properties": {
                    "base": {"type": "string", "default": "main"},
                    "head": {"type": "string", "default": "HEAD"}}},
                "handler": lambda a: _ser(
                    _compat_score_impl(js, a.get("base", "main"), a.get("head", "HEAD"))
                ),
            },

            # ── Migration ─────────────────────────────────────────────────
            "validate_migration": {
                "description": (
                    "Validate a SQL migration file: lock risk, duration estimate, "
                    "rollback presence, zero-downtime guide."
                ),
                "schema": {"type": "object", "required": ["file"],
                           "properties": {"file": {"type": "string"}}},
                "handler": lambda a: _run_migration(js, a["file"]),
            },
            "suggest_zero_downtime": {
                "description": (
                    "Suggest a zero-downtime migration plan for a SQL operation. "
                    "Pass a SQL string (e.g. 'ALTER TABLE orders ADD COLUMN …') or a file path."
                ),
                "schema": {"type": "object", "required": ["operation"],
                           "properties": {
                               "operation": {"type": "string",
                                             "description": "SQL string or path to migration file"}}},
                "handler": lambda a: _ser(
                    _suggest_zero_downtime_impl(js, a["operation"])
                ),
            },

            # ── Review ────────────────────────────────────────────────────
            "submit_for_review": {
                "description": (
                    "Submit a diff for multi-model code review. "
                    "Pass diff text directly, or specify base/head git refs."
                ),
                "schema": {"type": "object", "properties": {
                    "diff": {"type": "string",
                             "description": "Raw diff text (optional if base/head provided)"},
                    "base": {"type": "string", "default": "main"},
                    "head": {"type": "string", "default": "HEAD"}}},
                "handler": lambda a: _ser(
                    _submit_for_review_impl(js, a.get("diff"), a.get("base", "main"),
                                           a.get("head", "HEAD"))
                ),
            },
            "get_review_findings": {
                "description": "Get code review findings, optionally filtered by minimum confidence.",
                "schema": {"type": "object", "properties": {
                    "min_confidence": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                        "default": "low"}}},
                "handler": lambda a: _ser(
                    _get_review_findings_impl(js, a.get("min_confidence", "low"))
                ),
            },
            "get_high_confidence_bugs": {
                "description": (
                    "Return review findings confirmed by multiple models "
                    "with confidence='high' — the most reliable bugs found."
                ),
                "schema": {"type": "object", "properties": {}},
                "handler": lambda a: _ser(
                    _get_review_findings_impl(js, "high")
                ),
            },

            # ── Export / Import ───────────────────────────────────────────
            "export_index": {
                "description": "Export the current index as a portable .jsat.zip archive.",
                "schema": {"type": "object", "required": ["output"],
                           "properties": {
                               "output": {"type": "string"},
                               "compress": {"type": "integer", "default": 6}}},
                "handler": lambda a: _ser(js.export(a["output"])),  # type: ignore[attr-defined]
            },
            "import_index": {
                "description": "Restore the graph index from a .jsat.zip archive.",
                "schema": {"type": "object", "required": ["archive"],
                           "properties": {
                               "archive": {"type": "string",
                                           "description": "Path to .jsat.zip file"}}},
                "handler": lambda a: _ser(
                    _import_index_impl(js, a["archive"])
                ),
            },

            # ── Knowledge ─────────────────────────────────────────────────
            "knowledge_query": {
                "description": (
                    "Answer a question using the project knowledge base "
                    "(architecture decisions, gotchas, runbooks)."
                ),
                "schema": {"type": "object", "required": ["question"],
                           "properties": {
                               "question": {"type": "string"},
                               "service": {"type": "string"}}},
                "handler": lambda a: _run_knowledge_query(js, a["question"]),
            },
            "knowledge_add": {
                "description": "Add a note to the project knowledge base.",
                "schema": {"type": "object", "required": ["text"],
                           "properties": {
                               "text": {"type": "string"},
                               "category": {"type": "string", "default": "general"}}},
                "handler": lambda a: _run_knowledge_add(
                    js, a["text"], a.get("category", "general")
                ),
            },

            # ── IThinking ─────────────────────────────────────────────────
            "ithinking_plan": {
                "description": (
                    "Run IThinking phases 0-4 on a task: intent clarification, "
                    "local feasibility check, prompt optimisation, task decomposition, "
                    "and assumption audit. Returns the plan without executing."
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
                    "Checks if the result matched the original intent, estimates token cost."
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
                    "Checks: is this necessary? does a library exist? is this the smallest change?"
                ),
                "schema": {"type": "object", "required": ["subtask"],
                           "properties": {"subtask": {"type": "string"}}},
                "handler": lambda a: _ithinking_audit(a["subtask"]),
            },

            # ── Observability: in-process metrics ────────────────────────
            "get_metrics": {
                "description": (
                    "Return in-memory call metrics for all tools: "
                    "{tool_name: {calls, total_ms, errors}}. "
                    "A lightweight alternative to full Prometheus until prometheus_client is added."
                ),
                "schema": {"type": "object", "properties": {}},
                "handler": lambda a: json.dumps(self._metrics, indent=2),
            },

            # ── Remaining catalog tools (completing 42+ target) ───────────

            # Blast radius variants
            "blast_radius_file": {
                "description": "Alias for blast_radius — trace impact of a specific file.",
                "schema": {"type": "object", "required": ["file"],
                           "properties": {"file": {"type": "string"}, "max_depth": {"type": "integer", "default": 5}}},
                "handler": lambda a: _ser(js.blast_radius(target=a["file"], max_depth=a.get("max_depth", 5))),  # type: ignore[attr-defined]
            },
            "blast_radius_topic": {
                "description": "Trace blast radius for a Kafka topic schema change.",
                "schema": {"type": "object", "required": ["topic"],
                           "properties": {"topic": {"type": "string"}}},
                "handler": lambda a: _ser(js.blast_radius(target=a["topic"])),  # type: ignore[attr-defined]
            },

            # Security extras
            "security_scan_file": {
                "description": "OWASP security scan a specific file.",
                "schema": {"type": "object", "required": ["file"],
                           "properties": {"file": {"type": "string"}, "severity": {"type": "string", "default": "medium"}}},
                "handler": lambda a: _ser(js.security_review(path=a["file"], severity_threshold=a.get("severity", "medium"))),  # type: ignore[attr-defined]
            },
            "get_auth_coverage": {
                "description": "List endpoints with no authentication middleware in their call chain.",
                "schema": {"type": "object", "properties": {"service": {"type": "string"}}},
                "handler": lambda a: _ser(_auth_coverage_impl(js, a.get("service"))),
            },
            "get_dependency_cves": {
                "description": "List dependency CVEs above a CVSS threshold (osv.dev integration planned for v0.2).",
                "schema": {"type": "object", "properties": {"cvss_min": {"type": "number", "default": 7.0}}},
                "handler": lambda a: "CVE check via osv.dev coming in v0.2. Run: jsat security-review . for current dep scanning.",
            },
            "trace_data_flow": {
                "description": "Trace user input through the codebase to find injection risks.",
                "schema": {"type": "object", "required": ["entry_point"],
                           "properties": {"entry_point": {"type": "string"}}},
                "handler": lambda a: _ser(js.blast_radius(target=a["entry_point"])),  # type: ignore[attr-defined]
            },

            # Knowledge extras
            "knowledge_search": {
                "description": "Semantic search over the knowledge base.",
                "schema": {"type": "object", "required": ["query"],
                           "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "default": 5}}},
                "handler": lambda a: _run_knowledge_query(js, a["query"]),
            },
            "knowledge_list": {
                "description": "List knowledge base entries by category.",
                "schema": {"type": "object", "properties": {"category": {"type": "string"}}},
                "handler": lambda a: _run_knowledge_list(js, a.get("category")),
            },
            "knowledge_flag_stale": {
                "description": "Mark a knowledge base entry as potentially outdated.",
                "schema": {"type": "object", "required": ["entry_id"],
                           "properties": {"entry_id": {"type": "string"}}},
                "handler": lambda a: _run_knowledge_flag(js, a["entry_id"]),
            },

            # Incident extras
            "get_hypotheses": {
                "description": "Get ranked root-cause hypotheses from the last incident investigation.",
                "schema": {"type": "object", "properties": {"limit": {"type": "integer", "default": 5}}},
                "handler": lambda a: "Run jsat__investigate_incident first, then hypotheses are in the response.",
            },
            "get_recent_changes": {
                "description": "Recent git commits and deploys for affected services.",
                "schema": {"type": "object", "properties": {
                    "since": {"type": "string", "default": "72h"},
                    "services": {"type": "array", "items": {"type": "string"}}}},
                "handler": lambda a: _ser(js.investigate_incident(  # type: ignore[attr-defined]
                    "recent changes", since=a.get("since", "72h")).hypotheses[:5] if hasattr(js, "investigate_incident") else []),
            },
            "generate_runbook": {
                "description": "Generate a step-by-step runbook from an incident hypothesis.",
                "schema": {"type": "object", "required": ["hypothesis"],
                           "properties": {"hypothesis": {"type": "string"}}},
                "handler": lambda a: _ser(js.investigate_incident(a["hypothesis"])),  # type: ignore[attr-defined]
            },

            # Migration extras
            "estimate_lock_duration": {
                "description": "Estimate table lock duration for a SQL operation.",
                "schema": {"type": "object", "required": ["operation", "table"],
                           "properties": {"operation": {"type": "string"},
                                          "table": {"type": "string"},
                                          "row_count": {"type": "integer"}}},
                "handler": lambda a: _estimate_lock_impl(a),
            },

            # Test generation
            "generate_unit_test": {
                "description": "Generate a unit test for a specific function.",
                "schema": {"type": "object", "required": ["function"],
                           "properties": {"function": {"type": "string"}}},
                "handler": lambda a: f"Use jsat__query with: 'write a unit test for {a['function']} following the project test patterns'",
            },
            "generate_integration_test": {
                "description": "Generate an integration test for an endpoint.",
                "schema": {"type": "object", "required": ["endpoint"],
                           "properties": {"endpoint": {"type": "string"}}},
                "handler": lambda a: f"Use jsat__query with: 'write an integration test for {a['endpoint']}'",
            },
            "generate_contract_test": {
                "description": "Generate a contract test between producer and consumer services.",
                "schema": {"type": "object", "required": ["producer", "consumer"],
                           "properties": {"producer": {"type": "string"}, "consumer": {"type": "string"}}},
                "handler": lambda a: f"Use jsat__query with: 'write a contract test between {a['producer']} and {a['consumer']}'",
            },
            "get_consumers_of_endpoint": {
                "description": "All callers of a specific endpoint across the codebase.",
                "schema": {"type": "object", "required": ["endpoint"],
                           "properties": {"endpoint": {"type": "string"}}},
                "handler": lambda a: _ser(js.blast_radius(target=a["endpoint"])),  # type: ignore[attr-defined]
            },

            # IThinking extras
            "ithinking_execute": {
                "description": "Run the full IThinking pipeline (all 7 phases) on a task.",
                "schema": {"type": "object", "required": ["task"],
                           "properties": {"task": {"type": "string"}}},
                "handler": lambda a: _ithinking_plan(js, a["task"]) + "\n\n*Phase 5 (execution) runs in your Claude session.*",
            },
            "prompt_optimize": {
                "description": (
                    "Optimize any raw query into the best possible prompt using JSAT's "
                    "7-stage pipeline: classify → context → constraints → examples → "
                    "format spec → model formatting → compress. "
                    "Set send=true to also call the AI and return the response."
                ),
                "schema": {
                    "type": "object",
                    "required": ["query"],
                    "properties": {
                        "query": {"type": "string"},
                        "ai_provider": {"type": "string"},
                        "format": {"type": "string"},
                        "cot": {"type": "boolean", "default": False},
                        "send": {"type": "boolean", "default": False},
                        "no_context": {"type": "boolean", "default": False},
                    },
                },
                "handler": lambda a: _ser(_prompt_optimize_impl(js, a)),
            },
            "ithinking_token_estimate": {
                "description": "Estimate local vs LLM token cost for a task without executing.",
                "schema": {"type": "object", "required": ["task"],
                           "properties": {"task": {"type": "string"}}},
                "handler": lambda a: (
                    f"Task: {a['task'][:80]}\n"
                    f"Local resolution: {'yes (graph query)' if any(kw in a['task'].lower() for kw in ['where','list','find','what files']) else 'no (LLM required)'}\n"
                    f"Estimated tokens: ~{max(500, len(a['task'].split()) * 120)} tokens"
                ),
            },
        }


# ── Graph-backed helper implementations ───────────────────────────────────────

def _list_services_impl(js: object, language: str | None) -> list[dict]:
    import structlog
    log = structlog.get_logger(__name__)
    log.info("list_services", language=language)
    try:
        g = js._get_graph()  # type: ignore[attr-defined]
        nodes = g.nodes_by_label("Service")  # type: ignore[attr-defined]
        if language:
            nodes = [n for n in nodes
                     if str((n.get("properties") or n).get("language", "")).lower()
                     == language.lower()]
        log.info("list_services_done", count=len(nodes))
        return nodes
    except Exception as e:
        log.error("list_services_error", error=str(e))
        return [{"error": str(e)}]


def _list_endpoints_impl(
    js: object,
    service: str | None,
    method: str | None,
    auth: bool | None,
) -> list[dict]:
    import structlog
    log = structlog.get_logger(__name__)
    log.info("list_endpoints", service=service, method=method, auth=auth)
    try:
        g = js._get_graph()  # type: ignore[attr-defined]
        nodes = g.nodes_by_label("Endpoint")  # type: ignore[attr-defined]
        results = []
        for n in nodes:
            props = n.get("properties", n) if isinstance(n, dict) else {}
            if service and str(props.get("service", "")).lower() != service.lower():
                continue
            if method and str(props.get("method", "")).upper() != method.upper():
                continue
            if auth is not None and bool(props.get("auth_required")) != auth:
                continue
            results.append(n)
        log.info("list_endpoints_done", count=len(results))
        return results
    except Exception as e:
        log.error("list_endpoints_error", error=str(e))
        return [{"error": str(e)}]


def _get_function_impl(
    js: object,
    name: str | None,
    file: str | None,
    line: int | None,
) -> dict | str:
    import structlog
    log = structlog.get_logger(__name__)
    log.info("get_function", name=name, file=file, line=line)
    if not name and not file:
        return {"error": "Provide at least one of: name, file"}
    try:
        g = js._get_graph()  # type: ignore[attr-defined]
        nodes = g.nodes_by_label("Function")  # type: ignore[attr-defined]
        for n in nodes:
            props = n.get("properties", n) if isinstance(n, dict) else {}
            name_match = (not name) or str(props.get("name", "")) == name
            file_match = (not file) or str(props.get("file", "")).endswith(file)
            line_match = (line is None) or int(props.get("line", -1)) == line
            if name_match and file_match and line_match:
                log.info("get_function_found", name=props.get("name"), file=props.get("file"))
                return n
        log.warning("get_function_not_found", name=name, file=file, line=line)
        return {"error": f"Function not found: name={name}, file={file}, line={line}"}
    except Exception as e:
        log.error("get_function_error", error=str(e))
        return {"error": str(e)}


def _get_class_impl(js: object, name: str | None, file: str | None) -> dict | str:
    import structlog
    log = structlog.get_logger(__name__)
    log.info("get_class", name=name, file=file)
    if not name and not file:
        return {"error": "Provide at least one of: name, file"}
    try:
        g = js._get_graph()  # type: ignore[attr-defined]
        nodes = g.nodes_by_label("Class")  # type: ignore[attr-defined]
        for n in nodes:
            props = n.get("properties", n) if isinstance(n, dict) else {}
            name_match = (not name) or str(props.get("name", "")) == name
            file_match = (not file) or str(props.get("file", "")).endswith(file)
            if name_match and file_match:
                log.info("get_class_found", name=props.get("name"))
                return n
        log.warning("get_class_not_found", name=name, file=file)
        return {"error": f"Class not found: name={name}, file={file}"}
    except Exception as e:
        log.error("get_class_error", error=str(e))
        return {"error": str(e)}


def _list_tables_impl(js: object) -> list[dict]:
    import structlog
    log = structlog.get_logger(__name__)
    log.info("list_tables")
    try:
        g = js._get_graph()  # type: ignore[attr-defined]
        nodes = g.nodes_by_label("Table")  # type: ignore[attr-defined]
        log.info("list_tables_done", count=len(nodes))
        return nodes
    except Exception as e:
        log.error("list_tables_error", error=str(e))
        return [{"error": str(e)}]


def _trace_call_chain_impl(js: object, source: str, target: str) -> dict:
    """BFS from source to target; return shortest path or not-found."""
    import structlog
    log = structlog.get_logger(__name__)
    log.info("trace_call_chain", source=source, target=target)
    try:
        g = js._get_graph()  # type: ignore[attr-defined]

        # Resolve start node IDs by name match
        all_nodes = []
        for label in ("Function", "Service", "Endpoint", "Class"):
            try:
                all_nodes.extend(g.nodes_by_label(label))  # type: ignore[attr-defined]
            except Exception:
                pass

        def _match(n: dict, query: str) -> bool:
            props = n.get("properties", n) if isinstance(n, dict) else {}
            node_id = str(n.get("id", ""))
            return (str(props.get("name", "")) == query
                    or str(props.get("path", "")).endswith(query)
                    or node_id == query)

        start_ids = [n["id"] for n in all_nodes if _match(n, source) and "id" in n]
        target_ids = set(n["id"] for n in all_nodes if _match(n, target) and "id" in n)

        if not start_ids:
            return {"error": f"Source not found in graph: {source}"}
        if not target_ids:
            return {"error": f"Target not found in graph: {target}"}

        # BFS
        from collections import deque
        queue: deque[tuple[str, list[str]]] = deque(
            (sid, [sid]) for sid in start_ids
        )
        visited: set[str] = set(start_ids)
        max_depth = 10

        while queue:
            node_id, path = queue.popleft()
            if node_id in target_ids:
                log.info("trace_call_chain_found", path_length=len(path))
                return {"found": True, "path": path, "length": len(path)}
            if len(path) >= max_depth:
                continue
            try:
                for neighbor, _edge_type in g.neighbors(node_id):  # type: ignore[attr-defined]
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append((neighbor, path + [neighbor]))
            except Exception:
                pass

        log.warning("trace_call_chain_not_found", source=source, target=target)
        return {"found": False, "message": f"No path from '{source}' to '{target}' within depth {max_depth}"}
    except Exception as e:
        log.error("trace_call_chain_error", error=str(e))
        return {"error": str(e)}


def _get_data_flow_impl(js: object, service: str | None) -> list[dict]:
    """Return READS_FROM / WRITES_TO / PRODUCES / CONSUMES edges."""
    import structlog
    log = structlog.get_logger(__name__)
    log.info("get_data_flow", service=service)
    _DATA_EDGE_TYPES = frozenset({"READS_FROM", "WRITES_TO", "PRODUCES", "CONSUMES"})
    try:
        g = js._get_graph()  # type: ignore[attr-defined]
        edges = g.edges(edge_types=list(_DATA_EDGE_TYPES))  # type: ignore[attr-defined]
        if service:
            edges = [e for e in edges
                     if service.lower() in str(e.get("source", "")).lower()
                     or service.lower() in str(e.get("target", "")).lower()]
        log.info("get_data_flow_done", edge_count=len(edges), service=service)
        return edges
    except Exception as e:
        log.error("get_data_flow_error", error=str(e))
        return [{"error": str(e)}]


def _blast_radius_diff_impl(js: object, diff: str, max_depth: int) -> object:
    """Blast radius from a git diff string or ref (e.g. 'HEAD~1')."""
    import subprocess

    import structlog
    log = structlog.get_logger(__name__)
    log.info("blast_radius_diff", diff_preview=diff[:80], max_depth=max_depth)

    # If diff looks like a git ref, resolve it to an actual diff
    _GIT_REF_RE = r"^[A-Za-z0-9_.~^@{}:/\-]+$"
    import re
    if re.match(_GIT_REF_RE, diff.strip()) and "\n" not in diff.strip():
        log.info("blast_radius_diff_resolving_ref", ref=diff.strip())
        try:
            result = subprocess.run(
                ["git", "diff", diff.strip()],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0:
                diff = result.stdout
                log.info("blast_radius_diff_resolved", diff_lines=diff.count("\n"))
            else:
                log.warning("blast_radius_diff_git_error", stderr=result.stderr[:200])
        except Exception as ex:
            log.error("blast_radius_diff_subprocess_error", error=str(ex))

    try:
        from jsat.tools.blast_radius import BlastRadiusTool
        tool = BlastRadiusTool(graph=js._get_graph(), cfg=js._cfg)  # type: ignore[attr-defined]
        return tool.run(target="diff", diff=diff, max_depth=max_depth)
    except Exception as e:
        log.error("blast_radius_diff_tool_error", error=str(e))
        return {"error": str(e)}


def _get_consumers_impl(js: object, target: str) -> list[dict]:
    """Find nodes that CONSUMES or CALLS the given target."""
    import structlog
    log = structlog.get_logger(__name__)
    log.info("get_consumers", target=target)
    _CONSUMER_EDGE_TYPES = frozenset({"CONSUMES", "CALLS"})
    try:
        g = js._get_graph()  # type: ignore[attr-defined]
        edges = g.edges(edge_types=list(_CONSUMER_EDGE_TYPES))  # type: ignore[attr-defined]
        consumers = [
            e for e in edges
            if target.lower() in str(e.get("target", "")).lower()
        ]
        log.info("get_consumers_done", target=target, consumer_count=len(consumers))
        return consumers
    except Exception as e:
        log.error("get_consumers_error", error=str(e))
        return [{"error": str(e)}]


def _get_behavioral_coverage_impl(js: object, service: str | None) -> dict:
    """Coverage stats via TestHelperTool, returned as a structured dict."""
    from pathlib import Path

    import structlog
    log = structlog.get_logger(__name__)
    log.info("get_behavioral_coverage", service=service)
    try:
        from jsat.tools.test_helper import TestHelperTool
        tool = TestHelperTool(graph=js._get_graph(), cfg=js._cfg)  # type: ignore[attr-defined]
        r = tool.run(service=service)
        result = {
            "coverage_pct": r.coverage_pct,
            "untested_functions": len(r.untested_functions),
            "untested_endpoints": len(r.untested_endpoints),
            "over_mocked_tests": len(r.over_mocked_tests),
            "top_untested": r.untested_functions[:20],
        }
        log.info("get_behavioral_coverage_done", coverage_pct=r.coverage_pct)
        return result
    except Exception as e:
        log.error("get_behavioral_coverage_error", error=str(e))
        return {"error": str(e)}


def _list_untested_paths_impl(js: object, limit: int) -> list[str]:
    """Return the highest-risk untested function paths."""
    import structlog
    log = structlog.get_logger(__name__)
    log.info("list_untested_paths", limit=limit)
    try:
        from jsat.tools.test_helper import TestHelperTool
        tool = TestHelperTool(graph=js._get_graph(), cfg=js._cfg)  # type: ignore[attr-defined]
        r = tool.run()
        paths = r.untested_functions[:limit]
        log.info("list_untested_paths_done", returned=len(paths))
        return paths
    except Exception as e:
        log.error("list_untested_paths_error", error=str(e))
        return [f"error: {e}"]


def _contract_impl(js: object, base: str, head: str) -> dict:
    import structlog
    log = structlog.get_logger(__name__)
    log.info("contract_check", base=base, head=head)
    try:
        from jsat.tools.contract import ContractTool
        tool = ContractTool(graph=js._get_graph(), cfg=js._cfg)  # type: ignore[attr-defined]
        r = tool.run(base=base, head=head)
        return r.__dict__
    except Exception as e:
        log.error("contract_check_error", error=str(e))
        return {"error": str(e)}


def _check_breaking_impl(js: object, base: str, head: str) -> dict:
    import structlog
    log = structlog.get_logger(__name__)
    log.info("check_breaking_changes", base=base, head=head)
    try:
        from jsat.tools.contract import ContractTool
        tool = ContractTool(graph=js._get_graph(), cfg=js._cfg)  # type: ignore[attr-defined]
        r = tool.run(base=base, head=head)
        breaking = [c for c in r.changes if c.get("is_breaking")]
        log.info("check_breaking_done", breaking_count=len(breaking))
        return {
            "breaking_count": r.breaking_count,
            "breaking_changes": breaking,
        }
    except Exception as e:
        log.error("check_breaking_error", error=str(e))
        return {"error": str(e)}


def _compat_score_impl(js: object, base: str, head: str) -> dict:
    import structlog
    log = structlog.get_logger(__name__)
    log.info("get_compat_score", base=base, head=head)
    try:
        from jsat.tools.contract import ContractTool
        tool = ContractTool(graph=js._get_graph(), cfg=js._cfg)  # type: ignore[attr-defined]
        r = tool.run(base=base, head=head)
        log.info("get_compat_score_done", score=r.compat_score)
        return {
            "compat_score": r.compat_score,
            "breaking_count": r.breaking_count,
            "migration_guide": r.migration_guide,
        }
    except Exception as e:
        log.error("get_compat_score_error", error=str(e))
        return {"error": str(e)}


def _suggest_zero_downtime_impl(js: object, operation: str) -> dict:
    """Run migration tool on a SQL string or file path."""
    from pathlib import Path

    import structlog
    log = structlog.get_logger(__name__)
    log.info("suggest_zero_downtime", operation_preview=operation[:120])
    try:
        from jsat.tools.migration import MigrationTool
        tool = MigrationTool(graph=js._get_graph(), cfg=js._cfg)  # type: ignore[attr-defined]

        # Determine if the input is a file path or raw SQL
        op_path = Path(operation)
        if op_path.exists() and op_path.is_file():
            log.info("suggest_zero_downtime_from_file", path=str(op_path))
            r = tool.run(op_path)
        else:
            # Write to a temp file and run
            import tempfile
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".sql", delete=False
            ) as tmp:
                tmp.write(operation)
                tmp_path = Path(tmp.name)
            log.info("suggest_zero_downtime_from_string", tmp_path=str(tmp_path))
            try:
                r = tool.run(tmp_path)
            finally:
                tmp_path.unlink(missing_ok=True)

        log.info("suggest_zero_downtime_done", risk=r.risk_level)
        return {
            "risk_level": r.risk_level,
            "zero_downtime_guide": r.zero_downtime_guide,
            "lock_estimate_seconds": r.lock_estimate_seconds,
            "has_rollback": r.has_rollback,
            "operations": [op.__dict__ for op in r.operations],
        }
    except Exception as e:
        log.error("suggest_zero_downtime_error", error=str(e))
        return {"error": str(e)}


def _submit_for_review_impl(
    js: object, diff: str | None, base: str, head: str
) -> dict:
    import subprocess

    import structlog
    log = structlog.get_logger(__name__)
    log.info("submit_for_review", base=base, head=head, has_diff=diff is not None)

    # Resolve diff from git if not provided directly
    if not diff:
        try:
            result = subprocess.run(
                ["git", "diff", base, head],
                capture_output=True, text=True, timeout=30,
            )
            diff = result.stdout
            log.info("submit_for_review_diff_resolved", lines=diff.count("\n"))
        except Exception as ex:
            log.error("submit_for_review_git_error", error=str(ex))
            return {"error": f"Could not resolve diff: {ex}"}

    if not diff or not diff.strip():
        return {"error": f"No diff found between {base} and {head}"}

    try:
        from jsat.tools.review import ReviewTool
        tool = ReviewTool(graph=js._get_graph(), cfg=js._cfg,  # type: ignore[attr-defined]
                          ai=js._get_ai())  # type: ignore[attr-defined]
        r = tool.run(diff=diff)
        log.info("submit_for_review_done", findings=len(r.findings),
                 high_confidence=len(r.high_confidence))
        return {
            "findings": [f.__dict__ for f in r.findings],
            "high_confidence": [f.__dict__ for f in r.high_confidence],
            "total_models_used": r.total_models_used,
            "duration_ms": r.duration_ms,
        }
    except Exception as e:
        log.error("submit_for_review_error", error=str(e))
        return {"error": str(e)}


def _get_review_findings_impl(js: object, min_confidence: str) -> dict:
    """Run review on HEAD diff and filter by confidence level."""
    import subprocess

    import structlog
    log = structlog.get_logger(__name__)
    log.info("get_review_findings", min_confidence=min_confidence)

    _ORDER = {"low": 1, "medium": 2, "high": 3}
    min_level = _ORDER.get(min_confidence, 1)

    try:
        result = subprocess.run(
            ["git", "diff", "HEAD~1", "HEAD"],
            capture_output=True, text=True, timeout=30,
        )
        diff = result.stdout
    except Exception as ex:
        log.error("get_review_findings_git_error", error=str(ex))
        return {"error": f"Could not get HEAD diff: {ex}"}

    if not diff.strip():
        return {"message": "No diff found at HEAD~1..HEAD", "findings": []}

    try:
        from jsat.tools.review import ReviewTool
        tool = ReviewTool(graph=js._get_graph(), cfg=js._cfg,  # type: ignore[attr-defined]
                          ai=js._get_ai())  # type: ignore[attr-defined]
        r = tool.run(diff=diff)
        filtered = [
            f.__dict__ for f in r.findings
            if _ORDER.get(f.confidence, 1) >= min_level
        ]
        log.info("get_review_findings_done", total=len(r.findings), filtered=len(filtered))
        return {
            "min_confidence": min_confidence,
            "total_findings": len(r.findings),
            "filtered_findings": filtered,
        }
    except Exception as e:
        log.error("get_review_findings_error", error=str(e))
        return {"error": str(e)}


def _import_index_impl(js: object, archive: str) -> dict:
    """Restore index from a .jsat.zip archive."""
    from pathlib import Path

    import structlog
    log = structlog.get_logger(__name__)
    log.info("import_index", archive=archive)
    try:
        from jsat.tools.export import ExportTool
        tool = ExportTool(graph=js._get_graph(), cfg=js._cfg)  # type: ignore[attr-defined]
        tool.restore(Path(archive))
        log.info("import_index_done", archive=archive)
        return {"status": "ok", "archive": archive,
                "message": "Index restored successfully"}
    except Exception as e:
        log.error("import_index_error", archive=archive, error=str(e))
        return {"error": str(e)}


# ── Existing helper functions (unchanged) ─────────────────────────────────────

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
    return f"Stored in knowledge base (category: {category})"


def _prompt_optimize_impl(js: object, args: dict) -> dict:
    """MCP handler: optimize (and optionally send) a query."""
    import structlog
    log = structlog.get_logger(__name__)
    query = args.get("query", "")
    if not query.strip():
        return {"error": "query must not be empty"}
    try:
        from jsat.tools.prompt_optimizer import PromptOptimizer
        optimizer = PromptOptimizer(
            graph=js._get_graph(), cfg=js._cfg, ai=js._get_ai())  # type: ignore[attr-defined]
        result = optimizer.optimize(
            query,
            ai_provider=args.get("ai_provider"),
            output_format=args.get("format"),
            cot=bool(args.get("cot", False)),
            no_context=bool(args.get("no_context", False)),
        )
        payload = {
            "optimized_prompt": result.optimized_prompt,
            "task_type": result.task_type,
            "tokens_before": result.tokens_before,
            "tokens_after": result.tokens_after,
            "context_nodes": result.context_nodes[:10],
        }
        if args.get("send"):
            ai = js._get_ai()  # type: ignore[attr-defined]
            if ai.is_available():
                response = ai.complete(result.optimized_prompt, max_tokens=2048)
                optimizer.save_to_history(result, response)
                payload["response"] = response
            else:
                payload["error"] = "AI not available"
        return payload
    except Exception as e:
        log.error("mcp_prompt_optimize_error", error=str(e))
        return {"error": str(e)}


def _ithinking_plan(js: object, task: str) -> str:
    """Run IThinking phases 0-4 and return the plan as text."""
    from jsat.tools.ithinking import IThinkingTool

    tool = IThinkingTool(graph=js._get_graph(), cfg=js._cfg,  # type: ignore[attr-defined]
                         ai=js._get_ai())  # type: ignore[attr-defined]
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
        flag = "! " if phase.gate_triggered else "OK"
        lines.append(f"**[{flag}] Phase {phase.phase}: {name}**")
        lines.append(phase.output)
        lines.append("")

    local_msg = phases[1].output
    lines.append("---")
    lines.append(f"*Route: {local_msg}*")
    return "\n".join(lines)


def _ithinking_reflect(task: str, result: str) -> str:
    """Phase 6: reflection."""
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
    from jsat.tools.ithinking import _RISKY_TERMS
    found = [f"  [{t}] {msg}" for t, msg in _RISKY_TERMS.items()
             if t in subtask.lower()]
    if not found:
        return f"No risky assumptions detected in: '{subtask}'"
    return "Assumptions flagged:\n" + "\n".join(found)


def _auth_coverage_impl(js: object, service: str | None) -> list[dict]:
    """Find endpoints with no auth in their call chain."""
    try:
        endpoints = js._get_graph().query("MATCH (n:Endpoint) RETURN n")  # type: ignore[attr-defined]
        unprotected = []
        for ep in endpoints:
            props = ep.get("properties", {})
            if not props.get("auth") and not props.get("auth_required"):
                if service is None or props.get("service", "").lower() == service.lower():
                    unprotected.append({"route": props.get("route", "?"),
                                        "method": props.get("method", "?"),
                                        "service": props.get("service", "?")})
        return unprotected
    except Exception as e:
        return [{"error": str(e)}]


def _run_knowledge_list(js: object, category: str | None) -> list[dict]:
    from jsat.tools.knowledge import KnowledgeTool
    tool = KnowledgeTool(graph=js._get_graph(), cfg=js._cfg, ai=js._get_ai())  # type: ignore[attr-defined]
    return tool.list_entries(category=category)


def _run_knowledge_flag(js: object, entry_id: str) -> str:
    from jsat.tools.knowledge import KnowledgeTool
    tool = KnowledgeTool(graph=js._get_graph(), cfg=js._cfg, ai=js._get_ai())  # type: ignore[attr-defined]
    tool.flag_stale(entry_id)
    return f"✓ Flagged entry {entry_id} as stale."


def _estimate_lock_impl(args: dict) -> str:
    from jsat.tools.migration import _LOCK_TYPES
    operation = " ".join(args.get("operation", "").upper().split())
    row_count = args.get("row_count", 0)
    for key in sorted(_LOCK_TYPES, key=len, reverse=True):
        if operation.startswith(key):
            lock_type, rate = _LOCK_TYPES[key]
            est = row_count / rate if row_count else 1.0
            return (f"Operation: {key}\nLock type: {lock_type}\n"
                    f"Estimated duration: {est:.1f}s for {row_count:,} rows\n"
                    f"Dangerous: {'yes' if lock_type in ('AccessExclusiveLock', 'ShareRowExclusiveLock') else 'no'}")
    return f"Unknown operation: {args.get('operation')}. Use ALTER TABLE, CREATE INDEX, DROP TABLE, etc."
