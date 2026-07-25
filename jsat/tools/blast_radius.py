"""jsat.tools.blast_radius — Tool 4: Blast Radius Analyzer."""
from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

from jsat.tools import BaseTool

if TYPE_CHECKING:
    from jsat._models import BlastRadiusReport

# Severity classification by edge type
_BREAKING  = {"CALLS", "READS_FROM", "WRITES_TO", "CONSUMES", "PRODUCES"}
_DEGRADED  = {"IMPLEMENTS", "INHERITS"}
_WARNING   = {"DEPENDS_ON", "IMPORTS"}

SEVERITY_ORDER = {"breaking": 0, "degraded": 1, "warning": 2, "safe": 3}


def _classify(edge_type: str) -> str:
    if edge_type in _BREAKING:  return "breaking"
    if edge_type in _DEGRADED:  return "degraded"
    if edge_type in _WARNING:   return "warning"
    return "safe"


class BlastRadiusTool(BaseTool):
    """BFS traversal over the graph to trace downstream impact."""

    def run(
        self,
        target: str,
        diff: str | None = None,
        max_depth: int = 5,
        severity_filter: list[str] | None = None,
    ) -> BlastRadiusReport:
        import structlog
        from jsat._models import BlastRadiusReport, ImpactItem

        log = structlog.get_logger(__name__)
        log.info("blast_radius_start", target=target, max_depth=max_depth)
        t0 = time.monotonic()

        # Resolve start nodes from target (file path or node id)
        start_ids = self._resolve_target(target)
        if not start_ids:
            log.warning("blast_radius_no_start_nodes", target=target)

        impacts: list[ImpactItem] = []
        seen: set[str] = set(start_ids)

        for node_id, depth, edge_path in self._graph.bfs(start_ids, max_depth):
            if node_id in start_ids:
                continue
            if depth == 0:
                continue
            edge_type = edge_path[-1] if edge_path else "UNKNOWN"
            severity = _classify(edge_type)
            if severity_filter and severity not in severity_filter:
                continue

            node = self._graph.get_node(node_id)
            impacts.append(ImpactItem(
                node_id=node_id,
                node_type=node["label"] if node else "Unknown",
                node_name=node.get("properties", {}).get("name", node_id) if node else node_id,
                file=node.get("properties", {}).get("file") if node else None,
                severity=severity,  # type: ignore[arg-type]
                path=edge_path,
                depth=depth,
                reason=f"Reached via {edge_type}",
            ))

        # Sort: breaking first
        impacts.sort(key=lambda i: SEVERITY_ORDER.get(i.severity, 99))

        summary = {"breaking": 0, "degraded": 0, "warning": 0, "safe": 0}
        for imp in impacts:
            summary[imp.severity] = summary.get(imp.severity, 0) + 1

        duration_ms = round((time.monotonic() - t0) * 1000)
        log.info("blast_radius_done", impacts=len(impacts),
                 breaking=summary["breaking"], duration_ms=duration_ms)

        return BlastRadiusReport(
            target=target,
            impacts=impacts,
            summary=summary,
            mermaid_diagram=self._to_mermaid(target, impacts[:20]),
            duration_ms=duration_ms,
        )

    def _resolve_target(self, target: str) -> list[str]:
        """Find graph node ids matching the target (file path or node name)."""
        # Direct node lookup
        node = self._graph.get_node(target)
        if node:
            return [target]
        # Search by file path
        rows = self._graph.query(
            "SELECT id FROM nodes WHERE json_extract(properties,'$.file') = ?",
            {"file": target}
        )
        if rows:
            return [r["id"] for r in rows]
        # Search by name
        rows = self._graph.query(
            "SELECT id FROM nodes WHERE id LIKE ?",
            {"pattern": f"%::{target}"}
        )
        return [r["id"] for r in rows] if rows else [target]

    def _to_mermaid(self, target: str, impacts: list) -> str:
        lines = ["graph LR", f"    ROOT[\"{target}\"]"]
        colors = {"breaking": "style {id} fill:#ff6b6b",
                  "degraded": "style {id} fill:#ffd93d",
                  "warning":  "style {id} fill:#6bcb77",
                  "safe":     ""}
        for i, imp in enumerate(impacts):
            nid = f"N{i}"
            label = imp.node_name[:30]
            lines.append(f"    {nid}[\"{label}\"]")
            lines.append(f"    ROOT --> {nid}")
            if colors.get(imp.severity):
                lines.append(f"    {colors[imp.severity].format(id=nid)}")
        return "\n".join(lines)
