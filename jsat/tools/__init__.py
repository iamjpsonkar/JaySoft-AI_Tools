"""jsat.tools — Tool base class and registry."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jsat._ai import AIProvider
    from jsat._graph import GraphClient
    from jsat._models import JSATConfig


class BaseTool:
    """Minimal base all JSAT tools inherit from."""

    def __init__(self, graph: GraphClient, cfg: JSATConfig, ai: AIProvider | None = None) -> None:
        self._graph = graph
        self._cfg = cfg
        self._ai = ai
