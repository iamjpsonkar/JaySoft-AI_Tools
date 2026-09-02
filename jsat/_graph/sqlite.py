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


def _edge_id(source: str, target: str, type_: str) -> str:
    """The stable primary key for an edge. Single definition, because the
    capacity guard has to derive the same id the writer will insert."""
    return hashlib.sha256(f"{source}→{target}→{type_}".encode()).hexdigest()[:16]


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

        # graph.max_nodes / graph.max_edges were configurable and documented
        # but never checked anywhere, so GraphCapacityError could not fire.
        # They are enforced at the bulk-insert boundary — the only path mass
        # growth takes (the indexer batches 2000 at a time), which makes one
        # COUNT per batch free while keeping the documented limit real.
        self._max_nodes = int(getattr(cfg, "max_nodes", 0) or 0)
        self._max_edges = int(getattr(cfg, "max_edges", 0) or 0)

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
        edge_id = _edge_id(source, target, type)
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
        # Capability gap: the query TEXT is never recorded — it can embed user
        # identifiers. Only the fact that this backend could not serve it.
        try:
            from jsat._improve import record_signal
            record_signal(
                kind="capability_gap", source="graph", op="sqlite_query",
                detail={"reason": "unsupported_query", "backend": "sqlite"},
            )
        except Exception:
            pass
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

    _CAP_ID_CHUNK = 900   # stay under SQLITE_MAX_VARIABLE_NUMBER

    def _count_existing(self, table: str, ids: list[str]) -> int:
        """How many of `ids` are already rows in `table`."""
        found = 0
        for start in range(0, len(ids), self._CAP_ID_CHUNK):
            chunk = ids[start:start + self._CAP_ID_CHUNK]
            placeholders = ",".join("?" * len(chunk))
            row = self._conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE id IN ({placeholders})",  # noqa: S608
                tuple(chunk),
            ).fetchone()
            found += row[0]
        return found

    def _enforce_capacity(self, node_ids: list[str] | None = None,
                          edge_ids: list[str] | None = None) -> None:
        """Raise GraphCapacityError before a bulk insert would exceed a cap.

        Counts only ids that are NOT already present. Both bulk writers use
        `INSERT OR REPLACE`, so re-inserting an existing id replaces a row
        rather than adding one — counting the whole batch as growth made
        `jsat index --force` fail on any repo larger than about half the cap,
        even though the graph would not have grown at all.
        """
        from jsat._exceptions import GraphCapacityError
        if self._max_nodes and node_ids:
            unique = list(dict.fromkeys(node_ids))
            new = len(unique) - self._count_existing("nodes", unique)
            if new > 0:
                current = self.node_count()
                if current + new > self._max_nodes:
                    raise GraphCapacityError(
                        f"Adding {new} new node(s) would exceed "
                        f"graph.max_nodes ({self._max_nodes}); the graph "
                        f"already holds {current}.",
                        current_nodes=current, max_nodes=self._max_nodes,
                    )
        if self._max_edges and edge_ids:
            unique_e = list(dict.fromkeys(edge_ids))
            new_e = len(unique_e) - self._count_existing("edges", unique_e)
            if new_e > 0:
                current_e = self.edge_count()
                if current_e + new_e > self._max_edges:
                    raise GraphCapacityError(
                        f"Adding {new_e} new edge(s) would exceed "
                        f"graph.max_edges ({self._max_edges}); the graph "
                        f"already holds {current_e}.",
                        current_nodes=self.node_count(),
                        max_nodes=self._max_nodes,
                        current_edges=current_e, max_edges=self._max_edges,
                    )

    def bulk_add_nodes(self, nodes: list[dict[str, Any]]) -> None:
        self._enforce_capacity(
            node_ids=[str(n["id"]) for n in nodes])
        self._conn.executemany(
            "INSERT OR REPLACE INTO nodes (id, label, properties) VALUES (:id, :label, :props)",
            [{"id": n["id"], "label": n["label"], "props": json.dumps(n.get("properties", {}))}
             for n in nodes],
        )

    def bulk_add_edges(self, edges: list[dict[str, Any]]) -> None:
        self._enforce_capacity(
            edge_ids=[_edge_id(e["source"], e["target"], e["type"])
                      for e in edges])
        rows = []
        for e in edges:
            src, tgt, typ = e["source"], e["target"], e["type"]
            eid = _edge_id(src, tgt, typ)
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

    def checkpoint(self) -> None:
        """Move WAL contents into the main database file (see GraphClient)."""
        self._conn.commit()
        self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")

    def close(self) -> None:
        self._log.info("sqlite_graph_close")
        self._conn.close()
