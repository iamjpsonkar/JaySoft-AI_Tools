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
        log.info("test_helper_start", root=str(root), service=service, types=types)
        t0 = time.monotonic()

        test_files = self._find_tests(root)
        src_files = self._find_sources(root)

        untested = [str(s) for s in src_files if not self._has_test(s, test_files)]
        over_mocked = [str(t) for t in test_files if self._is_over_mocked(t)]
        file_coverage = round((len(src_files) - len(untested)) / max(len(src_files), 1) * 100, 1)

        # Try graph-based function-level coverage (preferred over file-level)
        tested_fns, total_fns = self._function_coverage(test_files)
        if total_fns > 0:
            coverage = round(tested_fns / total_fns * 100, 1)
            log.info("test_helper_function_coverage_used",
                     tested_fns=tested_fns, total_fns=total_fns,
                     fn_coverage_pct=coverage, file_coverage_pct=file_coverage)
        else:
            coverage = file_coverage
            log.debug("test_helper_file_coverage_used", file_coverage_pct=coverage)

        # Try graph-based endpoint gap detection
        untested_endpoints = self._untested_endpoints()

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
        return [
            p for p in root.rglob("*.py")
            if "test" in p.name.lower() or p.name.lower().startswith("test_")
        ]

    def _find_sources(self, root: Path) -> list[Path]:
        return [p for p in root.rglob("*.py")
                if "test" not in p.name.lower()
                and not any(ex in str(p) for ex in _EXCLUDES)]

    def _has_test(self, src: Path, tests: list[Path]) -> bool:
        stems = {src.stem, f"test_{src.stem}", f"{src.stem}_test"}
        return any(t.stem in stems or src.stem in t.stem for t in tests)

    def _is_over_mocked(self, test_file: Path) -> bool:
        try:
            content = test_file.read_text(errors="ignore").lower()
            mocks = content.count("mock")
            calls = content.count("(")
            return calls > 0 and mocks / calls > 0.6
        except Exception:
            return False

    def _untested_endpoints(self) -> list[str]:
        import structlog
        log = structlog.get_logger(__name__)
        try:
            rows = self._graph.query(
                "SELECT id, properties FROM nodes WHERE label = 'Endpoint'",
                {}
            )
            return [r.get("id", str(r)) for r in rows[:10]]
        except Exception as exc:
            log.warning("test_helper_endpoints_query_failed", error=str(exc))
            return []

    def _function_coverage(self, test_files: list[Path]) -> tuple[int, int]:
        """Return (tested_fn_count, total_fn_count) using graph + test file content."""
        import structlog
        log = structlog.get_logger(__name__)
        try:
            rows = self._graph.query(
                "SELECT id, properties FROM nodes WHERE label = 'Function'",
                {}
            )
            if not rows:
                log.debug("test_helper_function_coverage_no_rows")
                return 0, 0
            total = len(rows)
            # Build set of function names referenced in test files
            test_content = ""
            for tfile in test_files[:50]:
                try:
                    test_content += tfile.read_text(errors="ignore")
                except Exception:
                    pass
            tested = sum(
                1 for r in rows
                if (r.get("properties") or {}).get("name", "") in test_content
            )
            log.debug("test_helper_function_coverage", tested=tested, total=total)
            return tested, total
        except Exception as exc:
            log.warning("test_helper_function_coverage_failed", error=str(exc))
            return 0, 0
