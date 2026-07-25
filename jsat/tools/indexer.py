"""jsat.tools.indexer — Tool 1: Directory Indexer."""
from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Generator

from jsat.tools import BaseTool

if TYPE_CHECKING:
    from jsat._graph import GraphClient
    from jsat._models import IndexEvent, IndexResult, JSATConfig


class IndexerTool(BaseTool):
    """Walks a repo, parses source files, and populates the graph."""

    def run(
        self,
        path: Path,
        branch: str = "HEAD",
        force: bool = False,
        languages: list[str] | None = None,
    ) -> IndexResult:
        import structlog
        from jsat._models import IndexResult
        from jsat._parsers import get_parser, detect_language

        log = structlog.get_logger(__name__)
        log.info("indexer_start", path=str(path), branch=branch, force=force)

        t0 = time.monotonic()
        langs = set(languages or self._cfg.indexer.languages)
        exclude = set(self._cfg.indexer.exclude_patterns)
        max_kb = self._cfg.indexer.max_file_size_kb

        nodes_total = edges_total = files_done = 0

        # Walk files
        files = self._collect_files(path, langs, exclude, max_kb)
        log.info("indexer_files_found", count=len(files))

        batch_nodes: list[dict] = []
        batch_edges: list[dict] = []
        BATCH = 500

        for fpath in files:
            lang = detect_language(fpath)
            if not lang:
                continue
            parser = get_parser(lang)
            if not parser:
                continue
            try:
                result = parser.parse(fpath, path)
                batch_nodes.extend(result.nodes)
                batch_edges.extend(result.edges)
                nodes_total += len(result.nodes)
                edges_total += len(result.edges)
                files_done += 1

                if len(batch_nodes) >= BATCH:
                    self._graph.bulk_add_nodes(batch_nodes)  # type: ignore[attr-defined]
                    self._graph.bulk_add_edges(batch_edges)  # type: ignore[attr-defined]
                    self._graph.commit()  # type: ignore[attr-defined]
                    batch_nodes, batch_edges = [], []

            except Exception as e:
                log.warning("indexer_file_error", file=str(fpath), error=str(e))

        # Flush remaining
        if batch_nodes:
            self._graph.bulk_add_nodes(batch_nodes)  # type: ignore[attr-defined]
            self._graph.bulk_add_edges(batch_edges)  # type: ignore[attr-defined]
            self._graph.commit()  # type: ignore[attr-defined]

        duration_ms = round((time.monotonic() - t0) * 1000)
        log.info("indexer_done", nodes=nodes_total, edges=edges_total,
                 files=files_done, duration_ms=duration_ms)

        # Get git commit
        commit = self._get_commit(path)

        return IndexResult(
            nodes_indexed=nodes_total,
            edges_indexed=edges_total,
            duration_ms=duration_ms,
            languages=list(langs),
            commit=commit,
            repo_path=str(path),
        )

    def run_stream(
        self, path: Path, branch: str = "HEAD"
    ) -> Generator[IndexEvent, None, IndexResult]:
        """Stream progress events while indexing."""
        from jsat._models import IndexEvent
        # Emit a start event, then delegate to run()
        yield IndexEvent(phase="parsing", progress_pct=0.0, message="Starting indexer…",
                         files_done=0, files_total=0)
        result = self.run(path, branch)
        yield IndexEvent(phase="done", progress_pct=100.0,
                         message=f"Done: {result.nodes_indexed} nodes",
                         files_done=result.nodes_indexed, files_total=result.nodes_indexed)
        return result

    def _collect_files(
        self, root: Path, langs: set[str], exclude: set[str], max_kb: int
    ) -> list[Path]:
        from jsat._parsers import detect_language
        files = []
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if any(ex in p.parts or ex in str(p) for ex in exclude):
                continue
            if p.stat().st_size > max_kb * 1024:
                continue
            lang = detect_language(p)
            if lang and lang in langs:
                files.append(p)
        return files

    def _get_commit(self, path: Path) -> str:
        try:
            import git
            repo = git.Repo(path, search_parent_directories=True)
            return repo.head.commit.hexsha[:12]
        except Exception:
            return "unknown"
