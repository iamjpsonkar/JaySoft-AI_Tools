"""jsat._graph.neo4j — Neo4j graph backend (jsat[team] extra)."""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from jsat._graph import GraphClient


class Neo4jGraph(GraphClient):
    """
    Neo4j-backed graph using the official neo4j Python driver.
    Requires: pip install 'jsat[team]'
    Connection: Bolt protocol (bolt:// or neo4j+s://)
    """

    def __init__(self, cfg: Any) -> None:
        import structlog
        self._log = structlog.get_logger(__name__)

        try:
            import neo4j as _neo4j
        except ImportError as e:
            from jsat._exceptions import ProfileError
            raise ProfileError(
                "Neo4j backend requires the 'team' extra.\nInstall: pip install 'jsat[team]'",
                required_extra="team",
            ) from e

        uri = cfg.remote_uri or "bolt://localhost:7687"
        username = cfg.username or "neo4j"
        import os
        password = os.environ.get(cfg.password_env or "NEO4J_PASSWORD", "")

        self._driver = _neo4j.GraphDatabase.driver(
            uri, auth=(username, password)
        )
        # Verify connection
        try:
            self._driver.verify_connectivity()
            self._log.info("neo4j_init", uri=uri, username=username)
        except Exception as e:
            from jsat._exceptions import GraphConnectionError
            raise GraphConnectionError(
                f"Cannot connect to Neo4j at {uri}: {e}",
                uri=uri, detail=str(e),
            ) from e

    # ── Schema helpers ────────────────────────────────────────────────────────

    def _run(self, query: str, params: dict | None = None) -> list[dict[str, Any]]:
        from jsat._exceptions import GraphQueryError
        try:
            with self._driver.session() as session:
                result = session.run(query, params or {})
                return [dict(record) for record in result]
        except Exception as e:
            raise GraphQueryError(f"Query failed: {e}", query=query, detail=str(e)) from e

    # ── GraphClient interface ─────────────────────────────────────────────────

    def add_node(self, id: str, label: str, properties: dict[str, Any]) -> None:
        props_str = ", ".join(f"n.{k} = ${k}" for k in properties)
        cypher = (
            f"MERGE (n:{label} {{id: $id}}) "
            f"SET n.id = $id{', ' + props_str if props_str else ''}"
        )
        params = {"id": id, **{k: (v if not isinstance(v, (dict, list)) else str(v))
                               for k, v in properties.items()}}
        self._run(cypher, params)
        self._log.debug("neo4j_add_node", id=id, label=label)

    def add_edge(self, source: str, target: str, type: str,
                 properties: dict[str, Any] | None = None) -> None:
        props = properties or {}
        prop_str = " {" + ", ".join(f"{k}: ${k}" for k in props) + "}" if props else ""
        cypher = (
            f"MATCH (a {{id: $source}}), (b {{id: $target}}) "
            f"MERGE (a)-[r:{type}{prop_str}]->(b)"
        )
        self._run(cypher, {"source": source, "target": target, **props})
        self._log.debug("neo4j_add_edge", source=source, target=target, type=type)

    def get_node(self, id: str) -> dict[str, Any] | None:
        rows = self._run("MATCH (n {id: $id}) RETURN n", {"id": id})
        if not rows:
            return None
        node = rows[0]["n"]
        return {"id": node.get("id", id), "label": list(node.labels)[0] if node.labels else "",
                "properties": dict(node)}

    def outgoing_edges(self, node_id: str) -> list[tuple[str, str, dict[str, Any]]]:
        rows = self._run(
            "MATCH (a {id: $id})-[r]->(b) "
            "RETURN type(r) AS type, b.id AS target, properties(r) AS props",
            {"id": node_id},
        )
        return [(r["type"], r["target"], r.get("props", {})) for r in rows if r.get("target")]

    def bfs(self, start_ids: list[str], max_depth: int = 5) -> Iterator[tuple[str, int, list[str]]]:
        from collections import deque
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
                if target_id and target_id not in visited:
                    visited.add(target_id)
                    queue.append((target_id, depth + 1, path + [edge_type]))

    def query(self, cypher_like: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Execute Cypher directly on Neo4j."""
        return self._run(cypher_like, params)

    def node_count(self) -> int:
        rows = self._run("MATCH (n) RETURN count(n) AS c")
        return rows[0]["c"] if rows else 0

    def edge_count(self) -> int:
        rows = self._run("MATCH ()-[r]->() RETURN count(r) AS c")
        return rows[0]["c"] if rows else 0

    def bulk_add_nodes(self, nodes: list[dict[str, Any]]) -> None:
        self._log.debug("neo4j_bulk_add_nodes", count=len(nodes))
        for node in nodes:
            self.add_node(node["id"], node["label"], node.get("properties", {}))

    def bulk_add_edges(self, edges: list[dict[str, Any]]) -> None:
        self._log.debug("neo4j_bulk_add_edges", count=len(edges))
        for edge in edges:
            self.add_edge(edge["source"], edge["target"], edge["type"],
                          edge.get("properties", {}))

    def close(self) -> None:
        self._driver.close()
        self._log.info("neo4j_close")
