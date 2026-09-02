"""jsat.tools.export — Tool 12: Export/Import System."""
from __future__ import annotations

import json
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from jsat.tools import BaseTool

if TYPE_CHECKING:
    from jsat._models import ExportManifest

try:
    from jsat import __version__ as JSAT_VERSION
except ImportError:
    JSAT_VERSION = "unknown"
MANIFEST_FILE = "manifest.json"


class ExportTool(BaseTool):
    """Packages the graph + artifacts as a portable .jsat.zip."""

    def export(self, output: Path, compress_level: int = 6) -> ExportManifest:
        import structlog

        from jsat._models import ExportManifest

        log = structlog.get_logger(__name__)
        log.info("export_start", output=str(output))
        t0 = time.monotonic()

        output.parent.mkdir(parents=True, exist_ok=True)
        compression = zipfile.ZIP_DEFLATED

        manifest_data = {
            "jsat_version": JSAT_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "graph_backend": self._cfg.graph.backend,
            "nodes": self._graph.node_count(),
            "edges": self._graph.edge_count(),
        }

        with zipfile.ZipFile(output, "w", compression=compression,
                             compresslevel=compress_level) as zf:
            # Write manifest
            zf.writestr(MANIFEST_FILE, json.dumps(manifest_data, indent=2))

            # Write SQLite graph file if it exists.
            #
            # Checkpoint first. The graph runs in WAL mode, so rows committed
            # by this same process are still in the `-wal` sidecar and NOT in
            # the file being copied here. Without this, exporting straight
            # after an index (the SDK's `js.index(); js.export()` and the
            # export_index MCP tool both do exactly that) produced a valid,
            # readable, EMPTY database — while the manifest above reported the
            # true node count, so the archive looked fine until restored.
            if self._graph is not None:
                try:
                    self._graph.checkpoint()
                except Exception as e:  # never fail an export over this
                    log.warning("export_checkpoint_failed", error=str(e))
            graph_path = Path(self._cfg.graph.path)
            if graph_path.exists():
                zf.write(graph_path, "graph/graph.db")

            # Write INDEX.md if it exists
            index_md = Path(self._cfg.project_root) / ".jsat" / "INDEX.md"
            if index_md.exists():
                zf.write(index_md, "artifacts/INDEX.md")

            # Write .jsat.yaml config (will be written to temp for reading)
            config_yaml = Path(".jsat.yaml")
            if config_yaml.exists():
                zf.write(config_yaml, "config/.jsat.yaml")

        size_mb = output.stat().st_size / (1024 * 1024)
        duration_ms = round((time.monotonic() - t0) * 1000)
        log.info("export_done", output=str(output), size_mb=round(size_mb, 2),
                 duration_ms=duration_ms)

        return ExportManifest(
            path=str(output),
            size_mb=round(size_mb, 2),
            nodes=manifest_data["nodes"],
            edges=manifest_data["edges"],
            commit=manifest_data.get("commit", "unknown"),
            jsat_version=JSAT_VERSION,
            created_at=manifest_data["created_at"],
        )

    def _safe_extract_target(self, dest_root: Path, rel_name: str) -> Path:
        """Resolve a zip-entry-relative name to a path inside ``dest_root``.

        Rejects (raises ``ImportCorrupted``) any entry whose resolved path would
        escape ``dest_root`` — covers ``../`` traversal, absolute paths, and
        symlink-adjacent tricks. This is the same "resolve then verify
        containment" pattern used by ``jsat.tools._patch.apply_patch`` for
        sandboxed patch application.
        """
        from jsat._exceptions import ImportCorrupted

        target = (dest_root / rel_name).resolve()
        if target != dest_root and dest_root not in target.parents:
            raise ImportCorrupted(
                f"Unsafe archive entry escapes {dest_root}: {rel_name!r}",
                path=str(dest_root), detail=f"resolved target {target} is outside {dest_root}",
            )
        return target

    def restore(self, archive: Path, password: str | None = None,
                migrate: bool = False) -> None:
        import structlog

        from jsat._exceptions import ImportCorrupted, ImportVersionMismatch

        log = structlog.get_logger(__name__)
        log.info("import_start", archive=str(archive))

        if not archive.exists():
            raise ImportCorrupted(f"Archive not found: {archive}",
                                  path=str(archive), detail="file does not exist")

        try:
            with zipfile.ZipFile(archive, "r") as zf:
                # Read manifest
                try:
                    manifest_raw = zf.read(MANIFEST_FILE).decode()
                    manifest = json.loads(manifest_raw)
                except Exception as e:
                    raise ImportCorrupted(f"Manifest unreadable: {e}",
                                          path=str(archive), detail=str(e)) from e

                # Version check
                export_ver = manifest.get("jsat_version", "unknown")
                if export_ver != JSAT_VERSION and not migrate:
                    raise ImportVersionMismatch(
                        export_version=export_ver, current_version=JSAT_VERSION
                    )

                # Restore graph file.
                #
                # The database file is replaced wholesale, so any connection
                # already open on it must be closed first. SQLite runs in WAL
                # mode here (see _graph/sqlite.py pragmas), which means an open
                # handle also owns -wal/-shm sidecars describing the OLD file.
                # Leaving either behind makes the restored data invisible: the
                # stale WAL shadows the new main file and every read returns
                # the empty database that opening the graph had just created.
                # That is what made `jsat import` report nodes=0 for a
                # perfectly good archive.
                try:
                    graph_data = zf.read("graph/graph.db")
                    graph_path = Path(self._cfg.graph.path)
                    graph_path.parent.mkdir(parents=True, exist_ok=True)
                    if self._graph is not None:
                        try:
                            self._graph.close()
                        except Exception as e:  # a stuck handle must not abort
                            log.warning("import_graph_close_failed", error=str(e))
                    for sidecar in (
                        graph_path.with_name(graph_path.name + "-wal"),
                        graph_path.with_name(graph_path.name + "-shm"),
                    ):
                        try:
                            sidecar.unlink(missing_ok=True)
                        except OSError as e:
                            log.warning("import_sidecar_unlink_failed",
                                        path=str(sidecar), error=str(e))
                    graph_path.write_bytes(graph_data)
                    log.info("import_graph_restored", path=str(graph_path))
                except KeyError:
                    log.warning("import_no_graph_file", archive=str(archive))

                # Restore artifacts — guard against zip-slip path traversal:
                # a crafted entry (e.g. "artifacts/../../.ssh/authorized_keys" or an
                # absolute path) must not be allowed to write outside .jsat/.
                # Anchor artifacts to the CONFIGURED data dir, not to
                # ./.jsat relative to whatever cwd the caller happened to be
                # in — with JSAT_DATA_DIR set (or the hashed global store in
                # use) the old path wrote them somewhere nothing reads.
                dest_root = Path(self._cfg.graph.path).resolve().parent.parent
                for name in zf.namelist():
                    if name.startswith("artifacts/"):
                        target = self._safe_extract_target(
                            dest_root, name.removeprefix("artifacts/")
                        )
                        log.debug("import_artifact_extracting", entry=name,
                                  target=str(target))
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(zf.read(name))

        except (ImportCorrupted, ImportVersionMismatch):
            raise
        except Exception as e:
            raise ImportCorrupted(f"Failed to read archive: {e}",
                                  path=str(archive), detail=str(e)) from e

        log.info("import_done", archive=str(archive),
                 nodes=manifest.get("nodes", 0), edges=manifest.get("edges", 0))
