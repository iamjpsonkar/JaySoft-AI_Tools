"""jsat._graph.lightgraph — Pure-Python SQLite graph. No sqlean.py required."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import deque
from pathlib import Path
from typing import Any, Iterator

from jsat._graph import GraphClient


class LightGraph(GraphClient):
    """SQLite graph using only stdlib sqlite3. Identical interface to SQLiteGraph."""

    def __init__(self, cfg: Any) -> None:
        import structlog
        self._log = structlog.get_logger(__name__)
        db_path = getattr(cfg, "path", ":memory:")

        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._create_schema()
        self._conn.commit()
        self._log.info("lightgraph_init", path=db_path,
                       nodes=self.node_count(), edges=self.edge_count())

    def _create_schema(self) -> None:
        stmts = [
            "CREATE TABLE IF NOT EXISTS nodes (id TEXT PRIMARY KEY, label TEXT NOT NULL, properties TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS edges (id TEXT PRIMARY KEY, type TEXT NOT NULL, source_id TEXT NOT NULL, target_id TEXT NOT NULL, properties TEXT NOT NULL)",
            "CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id)",
            "CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id)",
            "CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(type)",
            "CREATE INDEX IF NOT EXISTS idx_nodes_label ON nodes(label)",
        ]
        for s in stmts:
            self._conn.execute(s)

    def add_node(self, id: str, label: str, properties: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO nodes (id, label, properties) VALUES (?,?,?)",
            (id, label, json.dumps(properties)),
        )

    def add_edge(self, source: str, target: str, type: str,
                 properties: dict[str, Any] | None = None) -> None:
        eid = hashlib.sha256(f"{source}→{target}→{type}".encode()).hexdigest()[:16]
        self._conn.execute(
            "INSERT OR REPLACE INTO edges (id, type, source_id, target_id, properties) VALUES (?,?,?,?,?)",
            (eid, type, source, target, json.dumps(properties or {})),
        )

    def get_node(self, id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT id, label, properties FROM nodes WHERE id=?", (id,)
        ).fetchone()
        if row is None:
            return None
        return {"id": row[0], "label": row[1], "properties": json.loads(row[2])}

    def outgoing_edges(self, node_id: str) -> list[tuple[str, str, dict[str, Any]]]:
        rows = self._conn.execute(
            "SELECT type, target_id, properties FROM edges WHERE source_id=?", (node_id,)
        ).fetchall()
        return [(r[0], r[1], json.loads(r[2])) for r in rows]

    def bfs(self, start_ids: list[str], max_depth: int = 5) -> Iterator[tuple[str, int, list[str]]]:
        visited: set[str] = set()
        queue: deque = deque()
        for sid in start_ids:
            if sid not in visited:
                visited.add(sid)
                queue.append((sid, 0, []))
        while queue:
            node_id, depth, path = queue.popleft()
            yield node_id, depth, path
            if depth >= max_depth:
                continue
            for edge_type, target_id, _ in self.outgoing_edges(node_id):
                if target_id not in visited:
                    visited.add(target_id)
                    queue.append((target_id, depth + 1, path + [edge_type]))

    def query(self, cypher_like: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        s = cypher_like.strip()
        if s.upper().startswith("SELECT"):
            return self._sql(s, list(params.values()) if params else None)
        m = re.fullmatch(r"MATCH\s+\(n:(\w+)\)\s+RETURN\s+n", s, re.IGNORECASE)
        if m:
            return self._sql("SELECT id, label, properties FROM nodes WHERE label=?", [m.group(1)])
        return []

    def _sql(self, sql: str, params: list | None = None) -> list[dict[str, Any]]:
        cur = self._conn.execute(sql, params or [])
        cols = [d[0] for d in cur.description] if cur.description else []
        results = []
        for row in cur.fetchall():
            rec = dict(zip(cols, row))
            if "properties" in rec and isinstance(rec["properties"], str):
                try:
                    rec["properties"] = json.loads(rec["properties"])
                except Exception:
                    pass
            results.append(rec)
        return results

    def bulk_add_nodes(self, nodes: list[dict[str, Any]]) -> None:
        self._conn.executemany(
            "INSERT OR REPLACE INTO nodes (id, label, properties) VALUES (?,?,?)",
            [(n["id"], n["label"], json.dumps(n.get("properties", {}))) for n in nodes],
        )

    def bulk_add_edges(self, edges: list[dict[str, Any]]) -> None:
        rows = []
        for e in edges:
            src, tgt, typ = e["source"], e["target"], e["type"]
            eid = hashlib.sha256(f"{src}→{tgt}→{typ}".encode()).hexdigest()[:16]
            rows.append((eid, typ, src, tgt, json.dumps(e.get("properties", {}))))
        self._conn.executemany(
            "INSERT OR REPLACE INTO edges (id, type, source_id, target_id, properties) VALUES (?,?,?,?,?)",
            rows,
        )

    def commit(self) -> None:
        self._conn.commit()

    def node_count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]

    def edge_count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]

    def close(self) -> None:
        self._log.info("lightgraph_close")
        self._conn.close()
