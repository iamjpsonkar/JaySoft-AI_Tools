"""jsat.tools.indexer — Tool 1: Directory Indexer."""
from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Generator

from jsat.tools import BaseTool

if TYPE_CHECKING:
    from jsat._models import IndexEvent, IndexResult


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
        from jsat._parsers import detect_language, get_parser

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

        result = IndexResult(
            nodes_indexed=nodes_total,
            edges_indexed=edges_total,
            duration_ms=duration_ms,
            languages=list(langs),
            commit=commit,
            repo_path=str(path),
        )

        # Write INDEX.md artifact — human+AI readable codebase map (plan.md Tool 1 spec)
        self._write_index_md(path, result)

        return result

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

    def _write_index_md(self, path: Path, result: object) -> None:
        """Write INDEX.md artifact — the human+AI-readable codebase map (plan.md Tool 1)."""
        import datetime
        try:
            jsat_dir = path / ".jsat"
            jsat_dir.mkdir(parents=True, exist_ok=True)

            services = self._graph.query("MATCH (n:Service) RETURN n")
            endpoints = self._graph.query("MATCH (n:Endpoint) RETURN n")
            tables = self._graph.query("MATCH (n:Table) RETURN n")
            topics = self._graph.query("MATCH (n:Topic) RETURN n")

            nodes = getattr(result, "nodes_indexed", 0)
            edges = getattr(result, "edges_indexed", 0)
            commit = getattr(result, "commit", "unknown")
            langs = getattr(result, "languages", [])

            lines = [
                f"# JSAT Index — {path.name}",
                f"> Generated: {datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')}"
                f" | Commit: {commit} | JSAT: 0.1.4",
                "",
                "## Overview",
                f"**Languages:** {', '.join(langs) or 'auto-detected'}  "
                f"| **Nodes:** {nodes:,} | **Edges:** {edges:,}",
                "",
            ]

            if services:
                lines += ["## Services", "| Service | Language | Entry Point |",
                          "|---------|----------|------------|"]
                for s in services[:20]:
                    p = s.get("properties", {})
                    lines.append(f"| {p.get('name','?')} | {p.get('language','?')} | {p.get('entry_point','')} |")
                lines.append("")

            if endpoints:
                lines += ["## API Endpoints", "| Method | Route | Auth | Service |",
                          "|--------|-------|------|---------|"]
                for e in endpoints[:30]:
                    p = e.get("properties", {})
                    auth = "✓" if p.get("auth") else "—"
                    lines.append(f"| {p.get('method','?')} | {p.get('route','?')} | {auth} | {p.get('service','')} |")
                lines.append("")

            if tables:
                lines += ["## Database Tables",
                          "| Table | Schema |", "|-------|--------|"]
                for t in tables[:20]:
                    p = t.get("properties", {})
                    lines.append(f"| {p.get('name','?')} | {p.get('schema','')} |")
                lines.append("")

            if topics:
                lines += ["## Kafka Topics",
                          "| Topic | Schema Format |", "|-------|--------------|"]
                for t in topics[:15]:
                    p = t.get("properties", {})
                    lines.append(f"| {p.get('name','?')} | {p.get('schema_format','')} |")
                lines.append("")

            lines += [
                "---",
                "*Generated by JSAT. Re-run `jsat index .` to refresh.*",
            ]

            index_path = jsat_dir / "INDEX.md"
            index_path.write_text("\n".join(lines), encoding="utf-8")
        except Exception as e:
            import structlog
            structlog.get_logger(__name__).warning("index_md_write_failed", error=str(e))

    def _get_commit(self, path: Path) -> str:
        try:
            import git
            repo = git.Repo(path, search_parent_directories=True)
            return repo.head.commit.hexsha[:12]
        except Exception:
            return "unknown"
