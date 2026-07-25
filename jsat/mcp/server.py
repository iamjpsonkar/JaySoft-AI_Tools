"""jsat.mcp.server — MCP (Model Context Protocol) server. v0.1: stdin/stdout JSON-RPC."""
from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from jsat._core import JSAT

from jsat.mcp.tools import MCP_TOOLS


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
        """Read JSON-RPC messages from stdin, write responses to stdout."""
        self._log.info("mcp_server_running", mode="stdin/stdout")
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                response = self._handle(msg)
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

    def _handle(self, msg: dict) -> dict:
        method = msg.get("method", "")
        id_ = msg.get("id", 1)

        if method == "initialize":
            return {"jsonrpc": "2.0", "id": id_, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "jsat", "version": "0.1.0"},
            }}

        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": id_,
                    "result": {"tools": self._list_tools()}}

        if method == "tools/call":
            params = msg.get("params", {})
            name = params.get("name", "")
            args = params.get("arguments", {})
            self._log.info("mcp_tool_call", name=name, args_keys=list(args.keys()))
            try:
                result = self._call(name, args)
                text = result if isinstance(result, str) else json.dumps(result, default=str)
                return {"jsonrpc": "2.0", "id": id_,
                        "result": {"content": [{"type": "text", "text": text}]}}
            except Exception as e:
                self._log.error("mcp_tool_error", name=name, error=str(e))
                return {"jsonrpc": "2.0", "id": id_,
                        "error": {"code": -32603, "message": str(e)}}

        return {"jsonrpc": "2.0", "id": id_,
                "error": {"code": -32601, "message": f"Method not found: {method}"}}

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
        return {
            "index_repo": {
                "description": "Build or refresh the codebase index.",
                "schema": {"type": "object", "properties": {
                    "path": {"type": "string"}, "force": {"type": "boolean"}}},
                "handler": lambda a: vars(js.index(path=a.get("path"), force=a.get("force", False))),
            },
            "blast_radius_file": {
                "description": "Compute blast radius for a file.",
                "schema": {"type": "object", "required": ["file"],
                           "properties": {"file": {"type": "string"}, "max_depth": {"type": "integer"}}},
                "handler": lambda a: vars(js.blast_radius(target=a["file"],
                                                            max_depth=a.get("max_depth", 5))),
            },
            "query": {
                "description": "Natural language query over the codebase.",
                "schema": {"type": "object", "required": ["question"],
                           "properties": {"question": {"type": "string"}}},
                "handler": lambda a: js.query(a["question"]).answer,
            },
            "investigate_incident": {
                "description": "Investigate a production incident.",
                "schema": {"type": "object", "required": ["description"],
                           "properties": {"description": {"type": "string"},
                                          "since": {"type": "string"}}},
                "handler": lambda a: vars(js.investigate_incident(
                    a["description"], since=a.get("since", "72h"))),
            },
            "get_index_status": {
                "description": "Return index node/edge counts.",
                "schema": {"type": "object", "properties": {}},
                "handler": lambda a: js.index_status,
            },
            "export_index": {
                "description": "Export current index to .jsat.zip.",
                "schema": {"type": "object", "required": ["output"],
                           "properties": {"output": {"type": "string"}}},
                "handler": lambda a: vars(js.export(a["output"])),
            },
            "get_jsat_version": {
                "description": "Return JSAT version and provider info.",
                "schema": {"type": "object", "properties": {}},
                "handler": lambda a: {
                    "version": "0.1.0",
                    "ai_provider": js._cfg.ai.provider,
                    "model": js._cfg.ai.model,
                    "graph_backend": js._cfg.graph.backend,
                },
            },
        }
