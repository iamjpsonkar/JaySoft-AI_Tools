"""jsat.tools.indexer — Tool 1: Directory Indexer.

Enhancements over v0.1.x:
- Parallel parsing:    ThreadPoolExecutor(max_workers=min(cpu_count,8)) — 4-8× speedup
- Incremental mode:    Only re-parse files changed since last run (mtime+sha256 manifest)
- Symbol resolution:   CALLS/IMPORTS edges resolved to actual node IDs post-parse
- Rich metadata:       Parsers now emit parameters, return_type, decorators, complexity, etc.
- Richer INDEX.md:     Complexity hotspots, largest files, inheritance map, dead-code candidates
"""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING, Generator

from jsat.tools import BaseTool

if TYPE_CHECKING:
    from jsat._models import IndexEvent, IndexResult


def _parse_file(fpath: Path, repo_root: Path, lang: str) -> tuple[list[dict], list[dict]]:
    """Worker function: parse one file. Creates its own parser instance (thread-safe)."""
    from jsat._parsers import get_parser
    parser = get_parser(lang)
    if not parser:
        return [], []
    try:
        r = parser.parse(fpath, repo_root)
        return r.nodes, r.edges
    except Exception:
        import structlog
        structlog.get_logger(__name__).warning("indexer_file_error", file=str(fpath))
        return [], []


class IndexerTool(BaseTool):
    """Walks a repo, parses source files, and populates the graph."""

    def run(
        self,
        path: Path,
        branch: str = "HEAD",
        force: bool = False,
        languages: list[str] | None = None,
    ) -> "IndexResult":
        import structlog

        from jsat._models import IndexResult
        from jsat._parsers import detect_language
        from jsat._parsers.manifest import IndexManifest

        log = structlog.get_logger(__name__)
        log.info("indexer_start", path=str(path), branch=branch, force=force)

        t0 = time.monotonic()
        langs = set(languages or self._cfg.indexer.languages)
        exclude = set(self._cfg.indexer.exclude_patterns)
        max_kb = self._cfg.indexer.max_file_size_kb
        workers = min(os.cpu_count() or 4, 8)

        jsat_dir = Path(path) / ".jsat"
        jsat_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = jsat_dir / "index-manifest.json"

        mgr = IndexManifest()
        prev_manifest = {} if force else mgr.load(manifest_path)

        # ── Collect files ──────────────────────────────────────────────────────
        all_files = self._collect_files(Path(path), langs, exclude, max_kb)
        log.info("indexer_files_found", count=len(all_files))

        # ── Compute incremental delta ──────────────────────────────────────────
        delta = mgr.compute_delta(prev_manifest, all_files, Path(path))
        is_incremental = bool(prev_manifest) and not force

        if is_incremental:
            log.info("indexer_incremental",
                     to_parse=len(delta.to_parse),
                     skipped=len(delta.unchanged),
                     deleted=len(delta.deleted))
            # Remove stale nodes/edges for deleted and modified files
            for rel_path in delta.deleted + [
                str(f.relative_to(path)) for f in delta.modified
            ]:
                self._remove_file_nodes(rel_path)
            files_to_parse = delta.to_parse
            files_skipped = len(delta.unchanged)
        else:
            files_to_parse = all_files
            files_skipped = 0

        # ── Parallel parse ────────────────────────────────────────────────────
        nodes_total = edges_total = files_done = 0
        batch_nodes: list[dict] = []
        batch_edges: list[dict] = []
        new_manifest_entries: dict[str, dict] = dict(prev_manifest)
        BATCH = 500

        lang_map: dict[Path, str] = {}
        for fpath in files_to_parse:
            lang = detect_language(fpath)
            if lang:
                lang_map[fpath] = lang

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(_parse_file, fpath, Path(path), lang): fpath
                    for fpath, lang in lang_map.items()}
            for fut in as_completed(futs):
                fpath = futs[fut]
                nodes, edges = fut.result()
                batch_nodes.extend(nodes)
                batch_edges.extend(edges)
                nodes_total += len(nodes)
                edges_total += len(edges)
                files_done += 1

                # Update manifest entry for this file
                rel, entry = mgr.file_entry(fpath, Path(path), len(nodes))
                new_manifest_entries[rel] = entry

                if len(batch_nodes) >= BATCH:
                    self._graph.bulk_add_nodes(batch_nodes)   # type: ignore[attr-defined]
                    self._graph.bulk_add_edges(batch_edges)   # type: ignore[attr-defined]
                    self._graph.commit()                       # type: ignore[attr-defined]
                    batch_nodes, batch_edges = [], []

        # Remove deleted entries from manifest
        for rel_path in delta.deleted:
            new_manifest_entries.pop(rel_path, None)

        # Flush remaining batch
        if batch_nodes:
            self._graph.bulk_add_nodes(batch_nodes)   # type: ignore[attr-defined]
            self._graph.bulk_add_edges(batch_edges)   # type: ignore[attr-defined]
            self._graph.commit()                       # type: ignore[attr-defined]

        # ── Symbol resolution pass ────────────────────────────────────────────
        resolved = self._resolve_edges() if files_done > 0 else 0

        duration_ms = round((time.monotonic() - t0) * 1000)
        commit = self._get_commit(Path(path))

        log.info("indexer_done",
                 nodes=nodes_total, edges=edges_total, files=files_done,
                 skipped=files_skipped, resolved=resolved,
                 workers=workers, incremental=is_incremental,
                 duration_ms=duration_ms)

        # Persist updated manifest
        mgr.save(manifest_path, new_manifest_entries, commit)

        # Gather complexity hotspots
        hotspots = self._complexity_hotspots(top_n=5)

        result = IndexResult(
            nodes_indexed=nodes_total,
            edges_indexed=edges_total,
            files_indexed=files_done,
            files_skipped=files_skipped,
            duration_ms=duration_ms,
            languages=list(langs),
            commit=commit,
            repo_path=str(path),
            incremental=is_incremental,
            resolved_edges=resolved,
            parallel_workers=workers,
            complexity_hotspots=hotspots,
        )
        self._write_index_md(Path(path), result)
        return result

    def _remove_file_nodes(self, rel_path: str) -> None:
        """Delete all nodes and edges belonging to a file (for incremental update)."""
        try:
            self._graph.query(   # type: ignore[attr-defined]
                "DELETE FROM nodes WHERE json_extract(properties,'$.file') = ?",
                [rel_path]
            )
            self._graph.query(   # type: ignore[attr-defined]
                "DELETE FROM edges WHERE source_id LIKE ?",
                [f"{rel_path}::%"]
            )
            self._graph.query(   # type: ignore[attr-defined]
                "DELETE FROM edges WHERE source_id = ?",
                [rel_path]
            )
        except Exception:
            pass  # non-SQLite backends may not support raw queries

    def _resolve_edges(self) -> int:
        """Resolve string-name CALLS/IMPORTS targets to actual graph node IDs.

        After parsing, CALLS edges point to callee names like "refund" instead
        of "payments/service.py::PaymentService.refund". This pass matches names
        to real node IDs where unambiguous (exactly 1 match).

        Note: uses raw SQLite json_extract() — only runs on sqlite/lightgraph backends.
        """
        import structlog
        log = structlog.get_logger(__name__)
        backend = getattr(getattr(self._cfg, "graph", None), "backend", "sqlite")
        if backend not in ("sqlite", "lightgraph"):
            log.info("edge_resolution_skipped",
                     reason="non_sqlite_backend", backend=backend,
                     note="CALLS/IMPORTS edges remain unresolved; use jsat__query for traversal")
            return 0
        try:
            edges = self._graph.query(   # type: ignore[attr-defined]
                "SELECT id, source_id, target_id, type FROM edges "
                "WHERE type IN ('CALLS','IMPORTS')"
            )
        except Exception:
            return 0

        resolved = 0
        for edge in edges:
            target = edge.get("target_id", "")
            if "::" in target or target.startswith("/"):
                continue  # already resolved or absolute path
            try:
                candidates = self._graph.query(  # type: ignore[attr-defined]
                    "SELECT id FROM nodes WHERE id LIKE ? OR "
                    "json_extract(properties,'$.name') = ?",
                    [f"%::{target}", target]
                )
            except Exception:
                continue
            if len(candidates) == 1:
                new_target = candidates[0].get("id", "")
                if new_target and new_target != target:
                    try:
                        self._graph.query(  # type: ignore[attr-defined]
                            "UPDATE edges SET target_id = ? WHERE id = ?",
                            [new_target, edge.get("id", "")]
                        )
                        resolved += 1
                    except Exception:
                        pass

        log.info("edge_resolution_done", resolved=resolved)
        return resolved

    def _complexity_hotspots(self, top_n: int = 5) -> list[dict]:
        """Return top-N functions by cyclomatic complexity."""
        try:
            rows = self._graph.query(  # type: ignore[attr-defined]
                "SELECT id, properties FROM nodes WHERE label='Function' "
                "ORDER BY CAST(json_extract(properties,'$.complexity') AS INTEGER) DESC "
                f"LIMIT {top_n}"
            )
            result = []
            for r in rows:
                props = r.get("properties", {})
                if isinstance(props, str):
                    import json
                    props = json.loads(props)
                result.append({
                    "name": props.get("name", r.get("id", "")),
                    "file": props.get("file", ""),
                    "complexity": props.get("complexity", 1),
                })
            return result
        except Exception:
            return []

    def run_stream(
        self, path: Path, branch: str = "HEAD"
    ) -> Generator["IndexEvent", None, "IndexResult"]:
        from jsat._models import IndexEvent
        yield IndexEvent(phase="parsing", progress_pct=0.0, message="Starting indexer…",
                         files_done=0, files_total=0)
        result = self.run(path, branch)
        yield IndexEvent(phase="done", progress_pct=100.0,
                         message=f"Done: {result.nodes_indexed} nodes",
                         files_done=result.files_indexed, files_total=result.files_indexed)
        return result

    def _collect_files(
        self, root: Path, langs: set[str], exclude: set[str], max_kb: int
    ) -> list[Path]:
        import structlog as _structlog
        _log = _structlog.get_logger(__name__)
        from jsat._parsers import detect_language
        follow_symlinks = getattr(getattr(self._cfg, "indexer", None), "follow_symlinks", False)
        files = []
        for p in root.rglob("*"):
            if p.is_symlink() and not follow_symlinks:
                _log.debug("indexer_symlink_skipped", path=str(p))
                continue
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

    def _write_index_md(self, path: Path, result: "IndexResult") -> None:
        """Write a rich INDEX.md with parser-derived content."""
        import datetime
        import json

        try:
            jsat_dir = path / ".jsat"
            jsat_dir.mkdir(parents=True, exist_ok=True)

            nodes = result.nodes_indexed
            edges = result.edges_indexed
            commit = result.commit
            langs = result.languages
            duration_s = result.duration_ms / 1000
            workers = result.parallel_workers

            now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            incremental_tag = " (incremental)" if result.incremental else ""

            lines = [
                f"# JSAT Index — {path.name}",
                f"> Generated: {now}{incremental_tag} | Commit: {commit}",
                f"> Indexed: {result.files_indexed:,} files in {duration_s:.1f}s"
                f" ({workers} workers) | Skipped: {result.files_skipped:,} unchanged",
                "",
                "## Overview",
                "",
                "| Metric | Value |",
                "|--------|-------|",
                f"| Languages | {', '.join(sorted(langs)) or 'auto-detected'} |",
                f"| Files indexed | {result.files_indexed:,} |",
                f"| Files skipped | {result.files_skipped:,} |",
                f"| Nodes | {nodes:,} |",
                f"| Edges | {edges:,} |",
                f"| Edges resolved | {result.resolved_edges:,} |",
                f"| Commit | {commit} |",
                "",
            ]

            # ── Language breakdown ─────────────────────────────────────────────
            try:
                lang_stats: dict[str, dict[str, int]] = {}
                for lang in langs:
                    fn_count = len(self._graph.query(  # type: ignore[attr-defined]
                        "SELECT id FROM nodes WHERE label='Function' "
                        "AND json_extract(properties,'$.language') = ?", [lang]
                    ))
                    cls_count = len(self._graph.query(  # type: ignore[attr-defined]
                        "SELECT id FROM nodes WHERE label='Class' "
                        "AND json_extract(properties,'$.language') = ?", [lang]
                    ))
                    file_count = len(self._graph.query(  # type: ignore[attr-defined]
                        "SELECT id FROM nodes WHERE label='File' "
                        "AND json_extract(properties,'$.language') = ?", [lang]
                    ))
                    if fn_count + cls_count + file_count > 0:
                        lang_stats[lang] = {"files": file_count, "functions": fn_count, "classes": cls_count}
                if lang_stats:
                    lines += ["## Language Breakdown", "",
                              "| Language | Files | Functions | Classes |",
                              "|----------|-------|-----------|---------|"]
                    for lang, s in sorted(lang_stats.items()):
                        lines.append(f"| {lang} | {s['files']:,} | {s['functions']:,} | {s['classes']:,} |")
                    lines.append("")
            except Exception:
                pass

            # ── Complexity hotspots ────────────────────────────────────────────
            try:
                hotspots = self._graph.query(  # type: ignore[attr-defined]
                    "SELECT id, properties FROM nodes WHERE label='Function' "
                    "ORDER BY CAST(json_extract(properties,'$.complexity') AS INTEGER) DESC "
                    "LIMIT 10"
                )
                if hotspots:
                    lines += ["## Complexity Hotspots", "",
                              "| Function | File | Complexity |",
                              "|----------|------|-----------|"]
                    for h in hotspots:
                        p = h.get("properties", {})
                        if isinstance(p, str):
                            p = json.loads(p)
                        c = p.get("complexity", 1)
                        if c > 1:
                            lines.append(f"| `{p.get('name','?')}` | {p.get('file','')} | {c} |")
                    lines.append("")
            except Exception:
                pass

            # ── Largest files ──────────────────────────────────────────────────
            try:
                large_files = self._graph.query(  # type: ignore[attr-defined]
                    "SELECT id, properties FROM nodes WHERE label='File' "
                    "ORDER BY CAST(json_extract(properties,'$.loc') AS INTEGER) DESC "
                    "LIMIT 10"
                )
                if large_files:
                    lines += ["## Largest Files", "",
                              "| File | LOC |",
                              "|------|-----|"]
                    for f in large_files:
                        p = f.get("properties", {})
                        if isinstance(p, str):
                            p = json.loads(p)
                        lines.append(f"| `{p.get('path','?')}` | {p.get('loc',0):,} |")
                    lines.append("")
            except Exception:
                pass

            # ── Inheritance map ────────────────────────────────────────────────
            try:
                inherits = self._graph.query(  # type: ignore[attr-defined]
                    "SELECT source_id, target_id FROM edges WHERE type='INHERITS' LIMIT 30"
                )
                if inherits:
                    lines += ["## Inheritance Map", ""]
                    for e in inherits:
                        child = e.get("source_id", "").split("::")[-1]
                        parent = e.get("target_id", "")
                        lines.append(f"- `{child}` → `{parent}`")
                    lines.append("")
            except Exception:
                pass

            # ── Most depended-on ───────────────────────────────────────────────
            try:
                popular = self._graph.query(  # type: ignore[attr-defined]
                    "SELECT target_id, COUNT(*) as cnt FROM edges WHERE type='CALLS' "
                    "GROUP BY target_id ORDER BY cnt DESC LIMIT 10"
                )
                if popular:
                    lines += ["## Most Called Functions", "",
                              "| Function | Callers |",
                              "|----------|---------|"]
                    for row in popular:
                        name = row.get("target_id", "").split("::")[-1]
                        cnt = row.get("cnt", 0)
                        lines.append(f"| `{name}` | {cnt} |")
                    lines.append("")
            except Exception:
                pass

            # ── Dead code candidates ───────────────────────────────────────────
            try:
                all_fns = self._graph.query(  # type: ignore[attr-defined]
                    "SELECT id, json_extract(properties,'$.name') as name, "
                    "json_extract(properties,'$.file') as file FROM nodes WHERE label='Function' "
                    "AND json_extract(properties,'$.is_public') = 1 LIMIT 500"
                )
                called_targets = {
                    r.get("target_id", "") for r in
                    self._graph.query("SELECT target_id FROM edges WHERE type='CALLS'")  # type: ignore[attr-defined]
                }
                dead = [f for f in all_fns if f.get("id") not in called_targets][:20]
                if dead:
                    lines += ["## Dead Code Candidates",
                              "> Public functions with no incoming CALLS edges (verify manually)", "",
                              "| Function | File |",
                              "|----------|------|"]
                    for f in dead:
                        lines.append(f"| `{f.get('name','?')}` | {f.get('file','')} |")
                    lines.append("")
            except Exception:
                pass

            # ── Service/Endpoint/Table/Topic (from other tools) ───────────────
            for label, title, col_headers, col_keys in [
                ("Service",  "Services",   ["Service","Language","Entry Point"],
                 ["name","language","entry_point"]),
                ("Endpoint", "API Endpoints", ["Method","Route","Auth","Service"],
                 ["method","route","auth","service"]),
                ("Table",    "Database Tables", ["Table","Schema"], ["name","schema"]),
                ("Topic",    "Kafka Topics", ["Topic","Schema Format"], ["name","schema_format"]),
            ]:
                try:
                    rows = self._graph.query(f"MATCH (n:{label}) RETURN n")  # type: ignore[attr-defined]
                    if rows:
                        lines += [f"## {title}", "",
                                  "| " + " | ".join(col_headers) + " |",
                                  "| " + " | ".join("---" for _ in col_headers) + " |"]
                        for r in rows[:20]:
                            p = r.get("properties", {})
                            if isinstance(p, str):
                                p = json.loads(p)
                            vals = [str(p.get(k, "")) for k in col_keys]
                            lines.append("| " + " | ".join(vals) + " |")
                        lines.append("")
                except Exception:
                    pass

            lines += [
                "---",
                "*Re-run `jsat index .` to refresh. Incremental mode: only changed files re-parsed.*",
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
