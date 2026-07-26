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

            # Write SQLite graph file if it exists
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
                                          path=str(archive), detail=str(e))

                # Version check
                export_ver = manifest.get("jsat_version", "unknown")
                if export_ver != JSAT_VERSION and not migrate:
                    raise ImportVersionMismatch(
                        export_version=export_ver, current_version=JSAT_VERSION
                    )

                # Restore graph file
                try:
                    graph_data = zf.read("graph/graph.db")
                    graph_path = Path(self._cfg.graph.path)
                    graph_path.parent.mkdir(parents=True, exist_ok=True)
                    graph_path.write_bytes(graph_data)
                    log.info("import_graph_restored", path=str(graph_path))
                except KeyError:
                    log.warning("import_no_graph_file", archive=str(archive))

                # Restore artifacts
                for name in zf.namelist():
                    if name.startswith("artifacts/"):
                        target = Path(".jsat") / name.removeprefix("artifacts/")
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(zf.read(name))

        except (ImportCorrupted, ImportVersionMismatch):
            raise
        except Exception as e:
            raise ImportCorrupted(f"Failed to read archive: {e}",
                                  path=str(archive), detail=str(e))

        log.info("import_done", archive=str(archive),
                 nodes=manifest.get("nodes", 0), edges=manifest.get("edges", 0))
