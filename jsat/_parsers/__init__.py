"""jsat._parsers — Parser factory and base class."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class ParseResult:
    """Container for nodes and edges extracted from a source file."""
    def __init__(self) -> None:
        self.nodes: list[dict[str, Any]] = []
        self.edges: list[dict[str, Any]] = []


class BaseParser(ABC):
    language: str  # "python" | "javascript" | "go"

    @abstractmethod
    def parse(self, file_path: Path, repo_root: Path) -> ParseResult: ...


def get_parser(language: str) -> BaseParser | None:
    """Return a parser for the language, or None if unsupported."""
    if language == "python":
        from jsat._parsers.python import PythonParser
        return PythonParser()
    if language in ("javascript", "typescript"):
        from jsat._parsers.javascript import JavaScriptParser
        return JavaScriptParser()
    if language == "go":
        from jsat._parsers.go import GoParser
        return GoParser()
    return None


def detect_language(file_path: Path) -> str | None:
    """Detect language from file extension."""
    return {
        ".py": "python", ".js": "javascript", ".jsx": "javascript",
        ".ts": "typescript", ".tsx": "typescript", ".go": "go",
        ".java": "java", ".rb": "ruby", ".rs": "rust",
    }.get(file_path.suffix.lower())


__all__ = ["ParseResult", "BaseParser", "get_parser", "detect_language"]
