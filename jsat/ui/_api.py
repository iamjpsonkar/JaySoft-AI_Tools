"""jsat.ui._api — request logic for the Studio server.

Every handler runs against a real ``JSAT`` instance and the *real* MCP tool
registry (``MCPServer._build_registry``), so a tool behaves in the browser
exactly as it does for an AI client. Structured screens (index, graph nodes)
read the graph directly for fast, tabular tables.
"""
from __future__ import annotations

import json
import time
from typing import Any

from jsat import JSAT
from jsat.mcp.server import MCPServer


class StudioAPI:
    """Stateless-ish facade over JSAT + the MCP registry, called per request."""

    def __init__(self, js: JSAT) -> None:
        self._js = js
        self._mcp: MCPServer | None = None

    def _registry(self) -> dict[str, dict[str, Any]]:
        if self._mcp is None:
            self._mcp = MCPServer(self._js)
        return self._mcp._registry  # noqa: SLF001 — Studio reuses the one registry

    # ── status ──────────────────────────────────────────────────────────────
    def status(self) -> dict[str, Any]:
        from jsat import __version__
        cfg = self._js._cfg  # noqa: SLF001 — internal config access for the UI
        ai = getattr(cfg, "ai", None)
        return {
            "jsat_version": __version__,
            "provider": getattr(ai, "provider", "none") if ai else "none",
            "graph_backend": getattr(cfg, "graph", {}).backend if hasattr(cfg, "graph") else "n/a",
            "tools": len(self._registry()),
        }

    def index(self) -> dict[str, Any]:
        info = dict(self._js.index_status)
        info["tools"] = len(self._registry())
        return info

    # node label names in the graph are capitalised: Function, File, …
    _LABEL_BY_NAME = {
        "function": "Function", "class": "Class", "endpoint": "Endpoint",
        "service": "Service", "table": "Table", "topic": "Topic", "file": "File",
    }

    def nodes(self, label: str, limit: int = 300) -> dict[str, Any]:
        proper = self._LABEL_BY_NAME.get(label.strip().lower())
        if proper is None:
            return {"error": f"unknown node label '{label}' (try: "
                             f"{', '.join(sorted(self._LABEL_BY_NAME))})"}
        try:
            g = self._js._get_graph()  # noqa: SLF001 — the UI needs raw graph access
            rows = g.nodes_by_label(proper)
        except Exception as e:  # noqa: BLE001 — not-yet-indexed repo must degrade
            return {"label": label, "count": 0, "rows": [],
                    "error": f"graph unavailable ({e}) — run `jsat index .`"}
        flat = []
        for r in rows:
            rec = dict(r.get("properties") or {})
            rec["id"] = r.get("id", "")
            rec["label"] = r.get("label", proper)
            flat.append(rec)
        return {"label": label, "count": len(flat), "rows": flat[:limit]}

    # ── tool catalog + execution ────────────────────────────────────────────
    def catalog(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for name, tool in self._registry().items():
            schema = tool.get("schema") or {}
            out.append({
                "name": name,
                "description": tool.get("description", ""),
                "required": list(schema.get("required", [])),
                "properties": sorted((schema.get("properties") or {}).keys()),
            })
        return sorted(out, key=lambda t: t["name"])

    def run_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        reg = self._registry()
        if name not in reg:
            return {"ok": False, "error": f"unknown tool '{name}'"}
        t0 = time.monotonic()
        try:
            result = reg[name]["handler"](args)
        except Exception as e:  # noqa: BLE001 — the UI must degrade per tool
            return {"ok": False, "error": str(e), "elapsed_ms": 0}
        elapsed = round((time.monotonic() - t0) * 1000)
        text = result if isinstance(result, str) else json.dumps(result, default=str)
        return {"ok": True, "result": text, "elapsed_ms": elapsed}

    def prompt(self, text: str) -> dict[str, Any]:
        from jsat.ui._intent import resolve
        intent = resolve(text)
        args = dict(intent.args)
        if not args and intent.tool == "query":
            args = {"question": text}
        out = self.run_tool(intent.tool, args)
        out.update({"intent": intent.tool, "confidence": intent.confidence,
                    "reason": intent.reason, "args": args})
        return out

    # ── sessions & plans (lighter than tools list) ─────────────────────────
    def sessions(self, limit: int = 25) -> list[dict[str, Any]]:
        try:
            from jsat import _sessions
            rows = []
            for s in _sessions.list_sessions(limit=limit):
                rows.append({
                    "id": getattr(s, "id", ""),
                    "skill": getattr(s, "skill", ""),
                    "task": str(getattr(s, "task", ""))[:120],
                    "status": getattr(s, "status", ""),
                    "path": str(getattr(s, "path", "")),
                })
            return rows
        except Exception as e:  # noqa: BLE001
            return [{"error": str(e)}]

    def plans(self) -> list[dict[str, Any]]:
        try:
            from jsat import _planner
            rows = []
            for s in _planner.list_plans():
                rows.append({
                    "id": getattr(s, "id", ""),
                    "skill": getattr(s, "skill", ""),
                    "task": str(getattr(s, "task", ""))[:120],
                    "status": getattr(s, "status", ""),
                    "path": str(getattr(s, "path", "")),
                })
            return rows
        except Exception as e:  # noqa: BLE001
            return [{"error": str(e)}]