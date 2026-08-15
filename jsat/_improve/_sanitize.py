"""jsat._improve._sanitize — the privacy filter for self-improvement signals.

Two independent stages:

* **Stage 1 (construction)** builds records only from provably JSAT-internal
  sources — relative paths under the ``jsat`` package, exception *type* names,
  and a finite allowlist of context keys. It never copies free-form strings.
* **Stage 2 (verification)** re-examines the finished record adversarially and
  drops it whole if anything looks like it came from the user's machine.

The rule throughout is **drop, never redact**. A regex substitution that misses
one case leaks proprietary data; dropping a record costs only a lost signal.
"""
from __future__ import annotations

import getpass
import hashlib
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

from jsat._secrets import looks_secret

SANITIZER_RULES_VERSION = 1

_EXTERNAL = "<external>"
_MAX_FRAMES = 12
_MAX_STR = 200
_MAX_RECORD_BYTES = 4096


def jsat_root() -> Path:
    """Absolute path of the installed ``jsat`` package directory."""
    import jsat
    return Path(jsat.__file__).resolve().parent


# ── Stage 1: construction ─────────────────────────────────────────────────────

# Literal message prefixes authored inside JSAT. Only the matched PREFIX is ever
# stored — the remainder of the message may embed user paths (e.g. IndexNotFound
# interpolates repo_path) and is discarded.
_MESSAGE_PREFIXES: tuple[str, ...] = (
    "No JSAT index found for",
    "Index is stale",
    "Index database is corrupted",
    "Config file not found",
    "Invalid config",
    "Required config key missing",
    "Unsupported language",
    "Ollama package not installed",
    "Ollama model",
    "Ollama error",
    "Neo4j requires",
    "Redis cache requires",
    "Embeddings require",
    "Security review requires",
    "Authentication failed for",
    "Rate limit exceeded for",
    "Request timed out after",
    "Context length exceeded for",
    "Unknown provider",
    "Unknown tool",
    "Skill not found",
    "Skill manifest invalid",
    "Skill execution failed",
    "Export failed",
    "Import failed",
    "Graph query failed",
    "Graph connection failed",
    "Cannot connect to",
)

# Context keys whose value domain is finite and owned by JSAT. Everything else is
# key-only. Note `got`, `path`, `repo_path`, `file`, `query` are NEVER stored —
# they carry the user's own data.
_CONTEXT_VALUE_ALLOWLIST: frozenset[str] = frozenset({
    "status_code", "provider", "language", "required_extra",
    "field", "expected", "budget_s", "elapsed_s", "timeout_seconds",
    "retry_after", "backend", "reason", "phase", "src_type",
})

_SAFE_STR_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789_.- ")


def _safe_scalar(key: str, value: Any) -> Any | None:
    """Return an allowlisted scalar, or None to drop the key."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        if key not in _CONTEXT_VALUE_ALLOWLIST:
            return None
        low = value.strip().lower()
        if not low or len(low) > 64:
            return None
        if not set(low) <= _SAFE_STR_CHARS:
            return None
        return low
    return None


def classify_frames(exc: BaseException | None) -> list[str]:
    """Render a traceback as JSAT-relative frames, collapsing external ones.

    A frame inside the package becomes ``jsat/tools/indexer.py:parse``; anything
    else becomes the literal marker ``<external>``. Because only the path
    *relative* to the package root is emitted, site-packages installs and editable
    checkouts render identically and the user's home directory cannot appear.
    """
    if exc is None:
        return []
    root = jsat_root()
    out: list[str] = []
    for frame in traceback.extract_tb(exc.__traceback__)[-30:]:
        try:
            rel = Path(frame.filename).resolve().relative_to(root)
            label = f"jsat/{rel.as_posix()}:{frame.name}"
        except (ValueError, OSError):
            label = _EXTERNAL
        if label == _EXTERNAL and out and out[-1] == _EXTERNAL:
            continue  # collapse runs of external frames
        out.append(label)
    return out[-_MAX_FRAMES:]


def classify_message(exc: BaseException | None) -> tuple[str | None, bool]:
    """Match an exception message against JSAT's own literal prefixes.

    Returns ``(message_class, unmatched)``. Never returns any part of the message
    beyond a prefix that is verbatim JSAT source text.
    """
    if exc is None:
        return None, False
    try:
        msg = str(exc)
    except Exception:
        return None, True
    for prefix in _MESSAGE_PREFIXES:
        if msg.startswith(prefix):
            return prefix, False
    return None, True


def sanitize_context(context: dict[str, Any] | None) -> dict[str, Any]:
    """Keep allowlisted values; for everything else keep the key + value type only."""
    if not isinstance(context, dict):
        return {}
    out: dict[str, Any] = {}
    for key, value in list(context.items())[:20]:
        if not isinstance(key, str) or not set(key.lower()) <= _SAFE_STR_CHARS:
            continue
        safe = _safe_scalar(key, value)
        out[key] = safe if safe is not None else f"<{type(value).__name__}>"
    return out


def fingerprint(
    kind: str, exc_type: str | None, message_class: str | None,
    op: str | None, frames: list[str],
) -> str:
    """Stable id for one issue.

    Excludes line numbers (they drift across releases and would shatter one bug
    into many clusters) and the JSAT version (so occurrences spanning versions
    aggregate into a single proposal).
    """
    canonical = json.dumps(
        [SANITIZER_RULES_VERSION, kind, exc_type, message_class, op, frames[-3:]],
        sort_keys=True,
    )
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:16]


def build_record(
    *, kind: str, source: str, exc: BaseException | None = None,
    op: str | None = None, detail: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Build a fully sanitized signal record, or None if it cannot be made safe."""
    from jsat._improve._store import SCHEMA_VERSION, time_now_iso

    exc_type = type(exc).__name__ if exc is not None else None
    if exc_type is not None and not exc_type.isidentifier():
        exc_type = None

    message_class, unmatched = classify_message(exc)
    frames = classify_frames(exc)

    ctx = getattr(exc, "context", None) if exc is not None else None
    merged: dict[str, Any] = sanitize_context(ctx)
    merged.update(sanitize_context(detail))

    safe_op = op if (isinstance(op, str) and set(op.lower()) <= _SAFE_STR_CHARS
                     and len(op) <= 64) else None

    import jsat
    record = {
        "schema_version": SCHEMA_VERSION,
        "ts": time_now_iso(),
        "kind": kind,
        "source": source,
        "exc_type": exc_type,
        "message_class": message_class,
        "unmatched_message": unmatched,
        "op": safe_op,
        "detail": merged,
        "frames": frames,
        "jsat_version": getattr(jsat, "__version__", "unknown"),
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "platform": sys.platform,
    }
    record["fingerprint"] = fingerprint(kind, exc_type, message_class, safe_op, frames)

    return record if verify_clean(record) else None


# ── Stage 2: adversarial verification ─────────────────────────────────────────

def _iter_strings(obj: Any):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _iter_strings(k)
            yield from _iter_strings(v)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            yield from _iter_strings(item)


def _machine_markers() -> list[str]:
    """Strings that would identify this machine or user if they leaked."""
    markers: list[str] = []
    for produce in (
        lambda: str(Path.home()),
        getpass.getuser,
        lambda: str(Path.cwd()),
        lambda: Path.cwd().name,
    ):
        try:
            value = produce()
        except Exception:
            continue
        if isinstance(value, str) and len(value) >= 3:
            markers.append(value)
    return markers


def verify_clean(payload: Any) -> bool:
    """Adversarial check on a finished payload. False means: drop it entirely.

    Applied to every signal record AND to every bundle file — including AI output,
    which is untrusted.
    """
    try:
        blob = json.dumps(payload, sort_keys=True) if not isinstance(payload, str) else payload
    except Exception:
        return False

    if not isinstance(payload, str) and len(blob.encode("utf-8")) > _MAX_RECORD_BYTES:
        return False

    for text in _iter_strings(payload) if not isinstance(payload, str) else [payload]:
        if not isinstance(payload, str) and len(text) > _MAX_STR:
            return False
        # 1. Any path-like string must be JSAT-relative.
        if "/" in text and text != _EXTERNAL:
            if text.startswith("/") or text.startswith("~/"):
                return False
            if not text.startswith("jsat/") and not _is_pathless(text):
                return False
        if len(text) > 2 and text[1] == ":" and text[2] in "\\/" and text[0].isalpha():
            return False  # Windows absolute path

    # 2. Machine/user identifiers.
    for marker in _machine_markers():
        if marker in blob:
            return False

    # 3. Secrets and high-entropy tokens.
    if looks_secret(blob):
        return False

    # 4. Any environment variable value (catches keys, tokens, usernames).
    return all(
        not (8 <= len(value) <= 4096 and value in blob)
        for value in os.environ.values()
    )


def _is_pathless(text: str) -> bool:
    """True for strings where '/' is incidental rather than a filesystem path."""
    return text.startswith("http://") or text.startswith("https://") or " " in text
