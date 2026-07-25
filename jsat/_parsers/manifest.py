"""jsat._parsers.manifest — Incremental index manifest: load, save, delta."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)

_MANIFEST_VERSION = 1


@dataclass
class DeltaResult:
    new: list[Path] = field(default_factory=list)
    modified: list[Path] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)   # rel-path strings
    unchanged: list[Path] = field(default_factory=list)

    @property
    def to_parse(self) -> list[Path]:
        return self.new + self.modified

    @property
    def total_changed(self) -> int:
        return len(self.new) + len(self.modified) + len(self.deleted)


class IndexManifest:
    """Tracks file mtime+sha256 to enable true incremental re-indexing."""

    def load(self, manifest_path: Path) -> dict[str, dict]:
        """Return {rel_path: {mtime, sha256, nodes}} or empty dict."""
        if not manifest_path.exists():
            log.debug("manifest_not_found", path=str(manifest_path))
            return {}
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            if raw.get("version") != _MANIFEST_VERSION:
                log.info("manifest_version_mismatch", expected=_MANIFEST_VERSION,
                         found=raw.get("version"), action="full_reindex")
                return {}
            data = raw.get("files", {})
            log.debug("manifest_loaded", files=len(data), path=str(manifest_path))
            return data
        except Exception as e:
            log.warning("manifest_load_failed", error=str(e), action="full_reindex")
            return {}

    def save(self, manifest_path: Path, files: dict[str, dict], commit: str = "unknown") -> None:
        """Write updated manifest to disk. Silent on failure."""
        try:
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"version": _MANIFEST_VERSION, "commit": commit,
                       "saved_at": time.time(), "files": files}
            manifest_path.write_text(json.dumps(payload, separators=(",", ":")),
                                     encoding="utf-8")
            log.debug("manifest_saved", files=len(files), path=str(manifest_path))
        except Exception as e:
            log.warning("manifest_save_failed", error=str(e))

    def compute_delta(
        self,
        manifest: dict[str, dict],
        current_files: list[Path],
        repo_root: Path,
    ) -> DeltaResult:
        """
        Compare manifest against current file list.
        Uses mtime as a fast pre-filter; only computes sha256 when mtime changed.
        """
        delta = DeltaResult()
        current_rel: set[str] = set()

        for fpath in current_files:
            try:
                rel = str(fpath.relative_to(repo_root))
            except ValueError:
                rel = str(fpath)
            current_rel.add(rel)

            prev = manifest.get(rel)
            try:
                mtime = fpath.stat().st_mtime
            except OSError:
                continue

            if prev is None:
                delta.new.append(fpath)
                log.debug("delta_new", file=rel)
                continue

            if abs(mtime - prev.get("mtime", 0)) < 0.001:
                delta.unchanged.append(fpath)
                continue

            # mtime changed — verify with sha256 to avoid false positives
            sha = _sha256(fpath)
            if sha != prev.get("sha256", ""):
                delta.modified.append(fpath)
                log.debug("delta_modified", file=rel)
            else:
                # mtime changed but content identical (touch, copy, etc.)
                delta.unchanged.append(fpath)

        # Detect deleted files
        for rel in manifest:
            if rel not in current_rel:
                delta.deleted.append(rel)
                log.debug("delta_deleted", file=rel)

        log.info("manifest_delta_computed",
                 new=len(delta.new), modified=len(delta.modified),
                 deleted=len(delta.deleted), unchanged=len(delta.unchanged))
        return delta

    def file_entry(self, fpath: Path, repo_root: Path, nodes_count: int) -> tuple[str, dict]:
        """Build a (rel_path, entry) tuple to update the manifest after parsing."""
        try:
            rel = str(fpath.relative_to(repo_root))
        except ValueError:
            rel = str(fpath)
        try:
            mtime = fpath.stat().st_mtime
        except OSError:
            mtime = 0.0
        return rel, {"mtime": mtime, "sha256": _sha256(fpath), "nodes": nodes_count}


def _sha256(path: Path) -> str:
    """SHA-256 of file content. Returns empty string on I/O error."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""
