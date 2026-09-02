"""jsat._graph — GraphClient ABC and shared data classes."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Node:
    id: str
    label: str  # "Function" | "Class" | "File" | "Service" | "Endpoint" | etc.
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class Edge:
    source_id: str
    target_id: str
    type: str  # "CALLS" | "IMPORTS" | "READS_FROM" | etc.
    properties: dict[str, Any] = field(default_factory=dict)


class GraphClient(ABC):
    """Contract all graph backends must implement."""

    @abstractmethod
    def add_node(self, id: str, label: str, properties: dict[str, Any]) -> None:
        """Upsert a node. If id exists, merge/replace properties."""
        ...

    @abstractmethod
    def add_edge(
        self,
        source: str,
        target: str,
        type: str,
        properties: dict[str, Any] | None = None,
    ) -> None:
        """Add a directed edge from source to target."""
        ...

    @abstractmethod
    def get_node(self, id: str) -> dict[str, Any] | None:
        """Return node record or None. Dict must have: id, label, properties."""
        ...

    @abstractmethod
    def outgoing_edges(self, node_id: str) -> list[tuple[str, str, dict[str, Any]]]:
        """Return [(edge_type, neighbor_id, edge_properties)] for node_id."""
        ...

    @abstractmethod
    def bfs(
        self,
        start_ids: list[str],
        max_depth: int = 5,
    ) -> Iterator[tuple[str, int, list[str]]]:
        """BFS traversal. Yields (node_id, depth, edge_path). Visits each node once."""
        ...

    @abstractmethod
    def query(
        self,
        cypher_like: str,
        params: list[Any] | dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Execute a Cypher-like query. SQLite backend translates to SQL.

        params: positional list (for SQLite ? placeholders) or named dict,
        or None for queries with no parameters.
        """
        ...

    def checkpoint(self) -> None:
        """Flush pending writes into the primary on-disk database.

        Matters for any caller that copies the database file rather than
        querying through this client. The SQLite backends run in WAL mode, so
        freshly committed rows live in a `-wal` sidecar until a checkpoint
        moves them across; copying the main file before that yields a file
        that is valid, readable and missing the data. Backends with no
        file-level representation may leave this as a no-op.
        """
        return None

    def edges(
        self,
        edge_types: list[str] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return edges as dicts with keys: source, target, type, properties.

        Optionally filtered to ``edge_types``. Concrete backends override this
        with a single indexed query; the fallback here walks nodes so a
        backend that only implements the abstract primitives still works.
        """
        wanted = set(edge_types) if edge_types else None
        out: list[dict[str, Any]] = []
        for row in self.query("MATCH (n) RETURN n"):
            node_id = row.get("id") if isinstance(row, dict) else None
            if not node_id:
                continue
            for edge_type, target_id, props in self.outgoing_edges(str(node_id)):
                if wanted is not None and edge_type not in wanted:
                    continue
                out.append({"source": node_id, "target": target_id,
                            "type": edge_type, "properties": props})
                if limit is not None and len(out) >= limit:
                    return out
        return out

    @abstractmethod
    def node_count(self) -> int: ...

    @abstractmethod
    def edge_count(self) -> int: ...

    @abstractmethod
    def close(self) -> None: ...

    def __enter__(self) -> GraphClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


__all__ = ["Node", "Edge", "GraphClient"]
