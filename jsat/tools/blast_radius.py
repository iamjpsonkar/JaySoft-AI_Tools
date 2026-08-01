"""jsat.tools.blast_radius — Tool 4: Blast Radius Analyzer."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from jsat._call_context import checkpoint
from jsat.tools import BaseTool

if TYPE_CHECKING:
    from jsat._models import BlastRadiusReport

# Severity classification by edge type
_BREAKING  = {"CALLS", "READS_FROM", "WRITES_TO", "CONSUMES", "PRODUCES"}
_DEGRADED  = {"IMPLEMENTS", "INHERITS"}
_WARNING   = {"DEPENDS_ON", "IMPORTS"}

SEVERITY_ORDER = {"breaking": 0, "degraded": 1, "warning": 2, "safe": 3}


def _classify(edge_type: str) -> str:
    if edge_type in _BREAKING:
        return "breaking"
    if edge_type in _DEGRADED:
        return "degraded"
    if edge_type in _WARNING:
        return "warning"
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

        checkpoint(f"blast_radius: resolving target '{target}'")
        # Resolve start nodes from target (file path or node id)
        start_ids = self._resolve_target(target)
        checkpoint(f"blast_radius: resolved {len(start_ids)} start node(s)")
        if not start_ids:
            log.warning("blast_radius_no_start_nodes", target=target)
            checkpoint("blast_radius: WARNING — no start nodes found for target")

        # Augment start_ids from diff if provided
        if diff is not None:
            checkpoint("blast_radius: expanding diff to find changed file nodes")
            diff_ids = self._start_ids_from_diff(diff)
            log.info("blast_radius_diff_ids", diff_ids_count=len(diff_ids))
            checkpoint(f"blast_radius: diff yielded {len(diff_ids)} additional node(s)")
            start_ids += diff_ids
            start_ids = list(dict.fromkeys(start_ids))  # deduplicate, preserve order
            checkpoint(f"blast_radius: {len(start_ids)} total start nodes after dedup")

        checkpoint(f"blast_radius: starting BFS from {len(start_ids)} node(s), max_depth={max_depth}")  # noqa: E501
        impacts: list[ImpactItem] = []
        visited: set[str] = set(start_ids)
        last_depth = -1
        depth_counts: dict[int, int] = {}

        for node_id, depth, edge_path in self._graph.bfs(start_ids, max_depth):
            if node_id in visited:
                continue
            visited.add(node_id)
            if depth == 0:
                continue
            if depth != last_depth:
                if last_depth >= 0:
                    checkpoint(
                        f"blast_radius: depth {last_depth} done — "
                        f"{depth_counts.get(last_depth, 0)} new node(s)"
                    )
                checkpoint(f"blast_radius: traversing depth {depth}/{max_depth}")
                last_depth = depth
            depth_counts[depth] = depth_counts.get(depth, 0) + 1

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

        if last_depth >= 0:
            checkpoint(
                f"blast_radius: depth {last_depth} done — "
                f"{depth_counts.get(last_depth, 0)} new node(s)"
            )
        checkpoint(f"blast_radius: BFS complete — {len(impacts)} impact(s) found")

        # Sort: breaking first
        checkpoint("blast_radius: sorting impacts by severity")
        impacts.sort(key=lambda i: SEVERITY_ORDER.get(i.severity, 99))

        summary = {"breaking": 0, "degraded": 0, "warning": 0, "safe": 0}
        for imp in impacts:
            summary[imp.severity] = summary.get(imp.severity, 0) + 1
        checkpoint(
            f"blast_radius: summary — "
            f"breaking={summary['breaking']} degraded={summary['degraded']} "
            f"warning={summary['warning']} safe={summary['safe']}"
        )

        checkpoint(f"blast_radius: generating Mermaid diagram ({min(len(impacts), 20)} nodes)")
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

    def _start_ids_from_diff(self, diff: str) -> list[str]:
        """Extract node IDs for all files changed in a unified diff."""
        import structlog
        log = structlog.get_logger(__name__)

        changed_files: set[str] = set()
        for line in diff.splitlines():
            if line.startswith("--- a/") or line.startswith("+++ b/"):
                path = line[6:].strip()
                if path != "/dev/null":
                    changed_files.add(path)

        log.debug("blast_radius_diff_changed_files", count=len(changed_files))

        ids: list[str] = []
        for fpath in changed_files:
            rows = self._graph.query(
                "SELECT id FROM nodes WHERE json_extract(properties,'$.file') LIKE ?",
                {"pattern": f"%{fpath}"}
            )
            matched = [r["id"] for r in rows]
            log.debug("blast_radius_diff_file_nodes", file=fpath, matched=len(matched))
            ids.extend(matched)
        return ids

    def _to_mermaid(self, target: str, impacts: list) -> str:
        lines = ["graph LR", f'    ROOT["{target}"]']
        for i, imp in enumerate(impacts):
            nid = f"N{i}"
            label = imp.node_name[:30]
            edge_label = imp.path[-1] if imp.path else ""
            lines.append(f'    {nid}["{label}"]')
            lines.append(f'    ROOT -->|"{edge_label}"| {nid}')
            sev_styles = {
                "breaking": f"    style {nid} fill:#ff6b6b",
                "degraded":  f"    style {nid} fill:#ffd93d",
                "warning":   f"    style {nid} fill:#6bcb77",
            }
            style_line = sev_styles.get(imp.severity, "")
            if style_line:
                lines.append(style_line)
        return "\n".join(lines)
