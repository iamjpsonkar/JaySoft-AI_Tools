"""jsat._improve._store — on-disk store for self-improvement signals.

Everything lives under a single global directory (``~/.jsat/improve/`` by default)
because signals describe JSAT itself, not the indexed repository. Deliberately NOT
``jsat_data_dir(repo)``, which can resolve to ``{repo}/.jsat/`` — i.e. inside the
user's private codebase.

stdlib-only: this module is imported from failure paths and must never drag in
optional dependencies.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

_SIGNALS = "signals.jsonl"
_CLUSTERS = "clusters.json"
_STATE = "state.json"
_BUNDLES = "bundles"

_MAX_BUNDLES = 20
_ROTATE_KEEP = 2500


def improve_dir() -> Path:
    """Root directory for improvement data.

    ``$JSAT_IMPROVE_DIR`` overrides (required for tests). Otherwise
    ``~/.jsat/improve/`` — no collision with the ``~/.jsat/<sha1_12>/`` per-repo
    dirs, since "improve" is not 12 hex characters.
    """
    override = os.environ.get("JSAT_IMPROVE_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".jsat" / "improve"


def bundles_dir() -> Path:
    return improve_dir() / _BUNDLES


def _safe_write(path: Path, data: str, *, extra_root: Path | None = None) -> None:
    """Atomically write ``data`` to ``path``, refusing any target outside the store.

    This is the structural guarantee that JSAT never patches its own installed
    source: every write in the self-improvement feature funnels through here, and
    anything resolving outside ``improve_dir()`` (or an explicit temp root) raises.
    """
    resolved = Path(path).expanduser().resolve()
    allowed = [improve_dir().resolve()]
    if extra_root is not None:
        allowed.append(Path(extra_root).resolve())
    if not any(_is_within(resolved, root) for root in allowed):
        raise ValueError(f"refusing to write outside the improve store: {resolved}")

    resolved.parent.mkdir(parents=True, exist_ok=True)
    tmp = resolved.with_suffix(resolved.suffix + ".tmp")
    tmp.write_text(data, encoding="utf-8")
    os.replace(tmp, resolved)  # atomic on POSIX and Windows


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def read_clusters() -> dict[str, dict[str, Any]]:
    """fingerprint -> cluster record."""
    data = _read_json(improve_dir() / _CLUSTERS, {})
    return data if isinstance(data, dict) else {}


def read_state() -> dict[str, Any]:
    data = _read_json(improve_dir() / _STATE, {})
    if not isinstance(data, dict):
        data = {}
    data.setdefault("schema_version", SCHEMA_VERSION)
    data.setdefault("last_nudge_ts", 0.0)
    data.setdefault("nudge_counts", {})
    data.setdefault("dropped_count", 0)
    return data


def write_state(state: dict[str, Any]) -> None:
    _safe_write(improve_dir() / _STATE, json.dumps(state, indent=2, sort_keys=True))


def write_clusters(clusters: dict[str, dict[str, Any]], *, max_clusters: int = 500) -> None:
    """Persist clusters, evicting the least significant when over cap."""
    if len(clusters) > max_clusters:
        ranked = sorted(
            clusters.items(),
            key=lambda kv: (kv[1].get("count", 0), kv[1].get("last_seen", "")),
            reverse=True,
        )
        clusters = dict(ranked[:max_clusters])
    _safe_write(improve_dir() / _CLUSTERS, json.dumps(clusters, indent=2, sort_keys=True))


def append_signals(records: list[dict[str, Any]], *, max_signals: int = 5000) -> None:
    """Append sanitized records to the JSONL audit trail, rotating when over cap."""
    if not records:
        return
    path = improve_dir() / _SIGNALS
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = "".join(json.dumps(r, sort_keys=True) + "\n" for r in records)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(lines)
    _rotate_if_needed(path, max_signals)


def _rotate_if_needed(path: Path, max_signals: int) -> None:
    try:
        if path.stat().st_size < 2_000_000:
            return
        kept = path.read_text(encoding="utf-8").splitlines()[-min(_ROTATE_KEEP, max_signals):]
        _safe_write(path, "\n".join(kept) + "\n")
    except Exception:
        pass


def merge_cluster(
    clusters: dict[str, dict[str, Any]], record: dict[str, Any], *, count: int = 1
) -> dict[str, dict[str, Any]]:
    """Fold one sanitized signal into its cluster, incrementing counters."""
    fp = record["fingerprint"]
    now = record.get("ts", "")
    existing = clusters.get(fp)
    if existing is None:
        clusters[fp] = {
            "fingerprint": fp,
            "kind": record.get("kind"),
            "exc_type": record.get("exc_type"),
            "message_class": record.get("message_class"),
            "op": record.get("op"),
            "frames": record.get("frames", []),
            "first_seen": now,
            "last_seen": now,
            "count": count,
            "versions": {record.get("jsat_version", "?"): count},
            "sources": {record.get("source", "?"): count},
            "sample_detail": record.get("detail", {}),
            "reported": False,
            "bundle_id": None,
        }
        return clusters

    existing["count"] = existing.get("count", 0) + count
    existing["last_seen"] = now or existing.get("last_seen", "")
    for field, key in (("versions", "jsat_version"), ("sources", "source")):
        bucket = existing.setdefault(field, {})
        name = record.get(key, "?")
        bucket[name] = bucket.get(name, 0) + count
    return clusters


def prune_bundles(max_bundles: int = _MAX_BUNDLES) -> None:
    """Keep only the newest ``max_bundles`` bundle directories."""
    root = bundles_dir()
    if not root.exists():
        return
    try:
        dirs = sorted(
            (p for p in root.iterdir() if p.is_dir()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for stale in dirs[max_bundles:]:
            for child in sorted(stale.rglob("*"), reverse=True):
                child.unlink() if child.is_file() else child.rmdir()
            stale.rmdir()
    except Exception:
        pass


def time_now_iso() -> str:
    """UTC timestamp at second precision — no sub-second timing side channel."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
