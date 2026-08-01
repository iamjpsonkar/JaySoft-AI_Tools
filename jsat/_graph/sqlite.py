"""jsat._graph.sqlite — SQLite + sqlite-vss graph backend. Always available."""
from __future__ import annotations

import contextlib
import hashlib
import json
import re
from collections import deque
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from jsat._graph import GraphClient

if TYPE_CHECKING:
    from jsat._models import GraphConfig


class SQLiteGraph(GraphClient):
    """SQLite-backed graph store using sqlean.py for extension support."""

    def __init__(self, cfg: GraphConfig) -> None:
        import structlog
        try:
            import sqlean as sqlite3  # type: ignore[import]
        except ImportError:
            import sqlite3  # type: ignore[assignment]  # fallback without extensions

        self._log = structlog.get_logger(__name__)
        db_path = getattr(cfg, "path", ".jsat/graph/graph.db")

        from pathlib import Path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")   # safe with WAL; 2× faster commits
        self._conn.execute("PRAGMA cache_size=-65536;")     # 64 MB page cache (was ~2 MB)
        self._conn.execute("PRAGMA temp_store=MEMORY;")     # temp tables in RAM
        self._conn.execute("PRAGMA mmap_size=268435456;")   # 256 MB memory-mapped I/O
        self._conn.execute("PRAGMA foreign_keys=ON;")
        # Allow up to 5s waiting on a locked DB before raising OperationalError.
        # Also register a no-op progress handler so Python's thread interrupt mechanism
        # (KeyboardInterrupt / thread cancellation) can surface during long queries.
        self._conn.execute("PRAGMA busy_timeout=5000;")
        self._conn.set_progress_handler(lambda: None, 10_000)
        self._create_schema()
        self._conn.commit()

        self._log.info("sqlite_graph_init", path=db_path,
                       nodes=self.node_count(), edges=self.edge_count())

    def _create_schema(self) -> None:
        stmts = [
            """CREATE TABLE IF NOT EXISTS nodes (
                id TEXT PRIMARY KEY, label TEXT NOT NULL, properties TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS edges (
                id TEXT PRIMARY KEY, type TEXT NOT NULL,
                source_id TEXT NOT NULL, target_id TEXT NOT NULL, properties TEXT NOT NULL
            )""",
            "CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id)",
            "CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id)",
            "CREATE INDEX IF NOT EXISTS idx_edges_type   ON edges(type)",
            "CREATE INDEX IF NOT EXISTS idx_nodes_label  ON nodes(label)",
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
        edge_id = hashlib.sha256(f"{source}→{target}→{type}".encode()).hexdigest()[:16]
        self._conn.execute(
            "INSERT OR REPLACE INTO edges (id, type, source_id, target_id, properties) "
            "VALUES (?,?,?,?,?)",
            (edge_id, type, source, target, json.dumps(properties or {})),
        )

    def get_node(self, id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT id, label, properties FROM nodes WHERE id=?", (id,)
        ).fetchone()
        if row is None:
            return None
        return {"id": row["id"], "label": row["label"],
                "properties": json.loads(row["properties"])}

    def outgoing_edges(self, node_id: str) -> list[tuple[str, str, dict[str, Any]]]:
        rows = self._conn.execute(
            "SELECT type, target_id, properties FROM edges WHERE source_id=?", (node_id,)
        ).fetchall()
        return [(r["type"], r["target_id"], json.loads(r["properties"])) for r in rows]

    def bfs(self, start_ids: list[str], max_depth: int = 5) -> Iterator[tuple[str, int, list[str]]]:
        visited: set[str] = set()
        queue: deque[tuple[str, int, list[str]]] = deque()
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

    def query(self, cypher_like: str, params: list[Any] | dict[str, Any] | None = None) -> list[dict[str, Any]]:  # noqa: E501
        s = cypher_like.strip()
        upper = s.upper()
        # Normalize params: always produce a list for positional ? placeholders
        def _as_list(p: list[Any] | dict[str, Any] | None) -> list[Any]:
            if p is None:
                return []
            if isinstance(p, dict):
                return list(p.values())
            return list(p)

        # Raw SQL pass-through for SELECT and write statements (DELETE, UPDATE, INSERT)
        if upper.startswith("SELECT"):
            return self.execute_sql(s, _as_list(params) or None)
        if upper.startswith(("DELETE", "UPDATE", "INSERT")):
            self._conn.execute(s, _as_list(params))
            self._conn.commit()
            return []

        # MATCH (n:Label) RETURN n
        m = re.fullmatch(r"MATCH\s+\(n:(\w+)\)\s+RETURN\s+n", s, re.IGNORECASE)
        if m:
            return self.execute_sql(
                "SELECT id, label, properties FROM nodes WHERE label=?", [m.group(1)]
            )
        # MATCH (n) WHERE n.id = $id RETURN n
        m2 = re.fullmatch(
            r"MATCH\s+\(n\)\s+WHERE\s+n\.id\s*=\s*\$id\s+RETURN\s+n", s, re.IGNORECASE
        )
        if m2:
            nid = params.get("id") if isinstance(params, dict) else None
            if nid:
                return self.execute_sql(
                    "SELECT id, label, properties FROM nodes WHERE id=?", [nid]
                )

        self._log.warning("sqlite_graph_unsupported_query", query=s)
        return []

    def execute_sql(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        cur = self._conn.execute(sql, params or [])
        cols = [d[0] for d in cur.description] if cur.description else []
        results = []
        for row in cur.fetchall():
            rec = dict(zip(cols, row, strict=False))
            if "properties" in rec and isinstance(rec["properties"], str):
                with contextlib.suppress(json.JSONDecodeError, TypeError):
                    rec["properties"] = json.loads(rec["properties"])
            results.append(rec)
        return results

    def executemany_sql(self, sql: str, params_list: list[Any]) -> None:
        """Execute a write statement for multiple rows in one batch (single commit)."""
        self._log.debug("sqlite_executemany_sql", sql=sql[:60], rows=len(params_list))
        self._conn.executemany(sql, params_list)
        self._conn.commit()

    def nodes_by_label(self, label: str) -> list[dict[str, Any]]:
        """Return all nodes with the given label."""
        return self.execute_sql(
            "SELECT id, label, properties FROM nodes WHERE label=?", [label]
        )

    def bulk_add_nodes(self, nodes: list[dict[str, Any]]) -> None:
        self._conn.executemany(
            "INSERT OR REPLACE INTO nodes (id, label, properties) VALUES (:id, :label, :props)",
            [{"id": n["id"], "label": n["label"], "props": json.dumps(n.get("properties", {}))}
             for n in nodes],
        )

    def bulk_add_edges(self, edges: list[dict[str, Any]]) -> None:
        rows = []
        for e in edges:
            src, tgt, typ = e["source"], e["target"], e["type"]
            eid = hashlib.sha256(f"{src}→{tgt}→{typ}".encode()).hexdigest()[:16]
            rows.append({"id": eid, "type": typ, "source_id": src, "target_id": tgt,
                          "props": json.dumps(e.get("properties", {}))})
        self._conn.executemany(
            "INSERT OR REPLACE INTO edges (id, type, source_id, target_id, properties) "
            "VALUES (:id, :type, :source_id, :target_id, :props)", rows,
        )

    def commit(self) -> None:
        self._conn.commit()

    def node_count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]

    def edge_count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]

    def close(self) -> None:
        self._log.info("sqlite_graph_close")
        self._conn.close()
