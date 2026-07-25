"""jsat.tools.test_helper — Tool 2: Test Intelligence Helper."""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from jsat.tools import BaseTool

_EXCLUDES = (".venv", "__pycache__", "dist", ".git", "node_modules", "build")


@dataclass
class TestGapReport:
    untested_endpoints: list[str]
    untested_functions: list[str]
    over_mocked_tests: list[str]
    coverage_pct: float
    duration_ms: int


class TestHelperTool(BaseTool):
    """Identifies test gaps by comparing source files to test files."""

    def run(self, path: Path | None = None, service: str | None = None,
            types: list[str] | None = None) -> TestGapReport:
        import structlog
        log = structlog.get_logger(__name__)
        root = path or Path.cwd()
        log.info("test_helper_start", root=str(root))
        t0 = time.monotonic()

        test_files = self._find_tests(root)
        src_files = self._find_sources(root)

        untested = [str(s) for s in src_files if not self._has_test(s, test_files)]
        over_mocked = [str(t) for t in test_files if self._is_over_mocked(t)]
        coverage = round((len(src_files) - len(untested)) / max(len(src_files), 1) * 100, 1)

        # Try graph-based endpoint gap detection
        untested_endpoints = self._untested_endpoints(log)

        duration_ms = round((time.monotonic() - t0) * 1000)
        log.info("test_helper_done", coverage_pct=coverage,
                 untested=len(untested), over_mocked=len(over_mocked),
                 duration_ms=duration_ms)

        return TestGapReport(
            untested_endpoints=untested_endpoints,
            untested_functions=untested,
            over_mocked_tests=over_mocked,
            coverage_pct=coverage,
            duration_ms=duration_ms,
        )

    def _find_tests(self, root: Path) -> list[Path]:
        return [p for p in root.rglob("*.py") if "test" in p.name.lower()]

    def _find_sources(self, root: Path) -> list[Path]:
        return [p for p in root.rglob("*.py")
                if "test" not in p.name.lower()
                and not any(ex in str(p) for ex in _EXCLUDES)]

    def _has_test(self, src: Path, tests: list[Path]) -> bool:
        return any(src.stem in t.name for t in tests)

    def _is_over_mocked(self, test_file: Path) -> bool:
        try:
            content = test_file.read_text(errors="ignore").lower()
            mocks = content.count("mock")
            calls = content.count("(")
            return calls > 0 and mocks / calls > 0.6
        except Exception:
            return False

    def _untested_endpoints(self, log: object) -> list[str]:
        try:
            rows = self._graph.query("MATCH (n:Endpoint) RETURN n")
            return [r.get("id", str(r)) for r in rows[:10]]
        except Exception:
            return []
