"""jsat.ui — JSAT Studio.

A zero-dependency browser UI and an optional terminal TUI that put a face on
every JSAT surface: index status, graph exploration, natural-language query,
blast radius, security, test gaps, API diff, review, incident, knowledge,
improve, prompt/token tools, sessions, plans and the full MCP tool catalog.

``jsat ui`` starts the browser app (stdlib-only, bind 127.0.0.1).
``jsat ui --tui`` starts the Textual terminal app when ``jsat[studio]`` is
installed. The Studio reuses the real MCP tool registry, so every tool behaves
exactly as it does for an AI client — one implementation, many faces.
"""
from __future__ import annotations

from .server import StudioServer, start_studio, stop_studio  # noqa: F401

__all__ = ["StudioServer", "start_studio", "stop_studio"]