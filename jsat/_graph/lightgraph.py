"""jsat._graph.lightgraph — Pure-Python SQLite graph. No sqlean.py required."""
from __future__ import annotations

import contextlib
import hashlib
import json
import re
import sqlite3
from collections import deque
from collections.abc import Iterator
from pathlib import Path
from typing import Any

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
        # graph.max_nodes / graph.max_edges were configurable and documented
        # but never checked anywhere, so GraphCapacityError could not fire.
        # They are enforced at the bulk-insert boundary — the only path mass
        # growth takes (the indexer batches 2000 at a time), which makes one
        # COUNT per batch free while keeping the documented limit real.
        self._max_nodes = int(getattr(cfg, "max_nodes", 0) or 0)
        self._max_edges = int(getattr(cfg, "max_edges", 0) or 0)

        self._log.info("lightgraph_init", path=db_path,
                       nodes=self.node_count(), edges=self.edge_count())

    def _create_schema(self) -> None:
        stmts = [
            "CREATE TABLE IF NOT EXISTS nodes "
            "(id TEXT PRIMARY KEY, label TEXT NOT NULL, properties TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS edges "
            "(id TEXT PRIMARY KEY, type TEXT NOT NULL, source_id TEXT NOT NULL, "
            "target_id TEXT NOT NULL, properties TEXT NOT NULL)",
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
            "INSERT OR REPLACE INTO edges (id, type, source_id, target_id, properties) "
            "VALUES (?,?,?,?,?)",
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

    def edges(
        self,
        edge_types: list[str] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return edges as dicts, optionally filtered by type.

        `type` is indexed, so the filter runs in SQL rather than in Python.
        """
        sql = "SELECT source_id, target_id, type, properties FROM edges"
        params: list[Any] = []
        if edge_types:
            sql += f" WHERE type IN ({','.join('?' * len(edge_types))})"
            params.extend(edge_types)
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        rows = self._conn.execute(sql, tuple(params)).fetchall()
        return [
            {"source": r["source_id"], "target": r["target_id"],
             "type": r["type"], "properties": json.loads(r["properties"])}
            for r in rows
        ]

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
        upper = s.upper()
        if upper.startswith("SELECT"):
            return self._sql(s, list(params.values()) if params else None)
        # Raw write statements (DELETE, UPDATE, INSERT)
        if upper.startswith(("DELETE", "UPDATE", "INSERT")):
            p = list(params.values()) if isinstance(params, dict) else (params or [])
            self._conn.execute(s, p)
            self._conn.commit()
            return []
        m = re.fullmatch(r"MATCH\s+\(n:(\w+)\)\s+RETURN\s+n", s, re.IGNORECASE)
        if m:
            return self._sql("SELECT id, label, properties FROM nodes WHERE label=?", [m.group(1)])
        return []

    def _sql(self, sql: str, params: list | None = None) -> list[dict[str, Any]]:
        cur = self._conn.execute(sql, params or [])
        cols = [d[0] for d in cur.description] if cur.description else []
        results = []
        for row in cur.fetchall():
            rec = dict(zip(cols, row, strict=False))
            if "properties" in rec and isinstance(rec["properties"], str):
                with contextlib.suppress(Exception):
                    rec["properties"] = json.loads(rec["properties"])
            results.append(rec)
        return results

    def _enforce_capacity(self, adding_nodes: int = 0, adding_edges: int = 0) -> None:
        """Raise GraphCapacityError before a bulk insert would exceed a cap."""
        from jsat._exceptions import GraphCapacityError
        if self._max_nodes and adding_nodes:
            current = self.node_count()
            if current + adding_nodes > self._max_nodes:
                raise GraphCapacityError(
                    f"Adding {adding_nodes} node(s) would exceed graph.max_nodes "
                    f"({self._max_nodes}); the graph already holds {current}.",
                    current_nodes=current, max_nodes=self._max_nodes,
                )
        if self._max_edges and adding_edges:
            current_e = self.edge_count()
            if current_e + adding_edges > self._max_edges:
                raise GraphCapacityError(
                    f"Adding {adding_edges} edge(s) would exceed graph.max_edges "
                    f"({self._max_edges}); the graph already holds {current_e}.",
                    current_nodes=self.node_count(), max_nodes=self._max_nodes,
                    current_edges=current_e, max_edges=self._max_edges,
                )

    def bulk_add_nodes(self, nodes: list[dict[str, Any]]) -> None:
        self._enforce_capacity(adding_nodes=len(nodes))
        self._conn.executemany(
            "INSERT OR REPLACE INTO nodes (id, label, properties) VALUES (?,?,?)",
            [(n["id"], n["label"], json.dumps(n.get("properties", {}))) for n in nodes],
        )

    def bulk_add_edges(self, edges: list[dict[str, Any]]) -> None:
        self._enforce_capacity(adding_edges=len(edges))
        rows = []
        for e in edges:
            src, tgt, typ = e["source"], e["target"], e["type"]
            eid = hashlib.sha256(f"{src}→{tgt}→{typ}".encode()).hexdigest()[:16]
            rows.append((eid, typ, src, tgt, json.dumps(e.get("properties", {}))))
        self._conn.executemany(
            "INSERT OR REPLACE INTO edges (id, type, source_id, target_id, properties) "
            "VALUES (?,?,?,?,?)",
            rows,
        )

    def commit(self) -> None:
        self._conn.commit()

    def node_count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]

    def edge_count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]

    def checkpoint(self) -> None:
        """Move WAL contents into the main database file (see GraphClient)."""
        self._conn.commit()
        self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")

    def close(self) -> None:
        self._log.info("lightgraph_close")
        self._conn.close()
