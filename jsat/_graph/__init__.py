"""jsat._graph — GraphClient ABC and shared data classes."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterator


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
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Execute a Cypher-like query. SQLite backend translates to SQL."""
        ...

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
