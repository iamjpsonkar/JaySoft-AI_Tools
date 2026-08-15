"""jsat.tools.improve — diagnose recorded friction and propose a patch to JSAT.

Reads the signal clusters written by ``jsat._improve``, asks the configured AI
provider to explain the top issue and produce a unified diff against JSAT's own
source, validates that diff in a throwaway sandbox, and writes an inert
"improvement bundle" the maintainer can turn into a PR.

Safety: this module never writes to the installed ``jsat`` package. Every write
goes through ``_store._safe_write``, which refuses targets outside the improve
store. The patch is LLM output and stays inert data until a human reviews it.
"""
from __future__ import annotations

import ast
import hashlib
import json
import urllib.parse
from pathlib import Path
from typing import Any

import structlog

from jsat._improve._sanitize import jsat_root, verify_clean
from jsat._improve._store import (
    _safe_write,
    bundles_dir,
    prune_bundles,
    read_clusters,
    read_state,
    time_now_iso,
    write_clusters,
)
from jsat.tools._patch import validate_patch

log = structlog.get_logger(__name__)

_MAX_CONTEXT_BYTES = 60_000
_CONTEXT_WINDOW = 40          # lines either side of the target function
_MAX_URL = 6000


def install_kind() -> str:
    """Whether JSAT is running from an editable checkout or site-packages."""
    try:
        pyproject = jsat_root().parent / "pyproject.toml"
        if pyproject.exists() and 'name = "jsat"' in pyproject.read_text(encoding="utf-8"):
            return "editable"
    except Exception:
        pass
    return "site-packages"


def list_clusters(*, unreported_only: bool = False) -> list[dict[str, Any]]:
    """Recorded issue clusters, most frequent first."""
    clusters = list(read_clusters().values())
    if unreported_only:
        clusters = [c for c in clusters if not c.get("reported")]
    return sorted(clusters, key=lambda c: c.get("count", 0), reverse=True)


def select_target(cluster_id: str | None = None) -> dict[str, Any] | None:
    """Pick the cluster to work on: an explicit id, else the top unreported one."""
    clusters = read_clusters()
    if cluster_id:
        for fp, cluster in clusters.items():
            if fp.startswith(cluster_id):
                return cluster
        return None
    candidates = [c for c in clusters.values() if not c.get("reported")]
    return max(candidates, key=lambda c: c.get("count", 0)) if candidates else None


# ── source context ────────────────────────────────────────────────────────────

def _function_window(source: str, func_name: str) -> tuple[int, int] | None:
    """Line span of ``func_name`` found by AST walk.

    Located by NAME rather than by the recorded line number: fingerprints
    deliberately exclude line numbers because they drift between releases.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            start = getattr(node, "lineno", 1)
            end = getattr(node, "end_lineno", start) or start
            return start, end
    return None


def gather_context(cluster: dict[str, Any]) -> dict[str, str]:
    """Read the JSAT source around each recorded frame. Read-only."""
    root = jsat_root()
    snippets: dict[str, str] = {}
    total = 0

    for frame in cluster.get("frames", []):
        if frame == "<external>" or ":" not in frame:
            continue
        rel_path, _, func = frame.partition(":")
        rel = rel_path[len("jsat/"):] if rel_path.startswith("jsat/") else rel_path
        path = root / rel
        if not path.exists() or rel_path in snippets:
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except Exception:
            continue

        lines = source.splitlines()
        span = _function_window(source, func)
        if span:
            start = max(span[0] - 1 - 3, 0)
            end = min(span[1] + 3, len(lines))
        else:
            start, end = 0, min(_CONTEXT_WINDOW * 2, len(lines))

        numbered = "\n".join(
            f"{i + 1:5d}  {lines[i]}" for i in range(start, end)
        )
        if total + len(numbered) > _MAX_CONTEXT_BYTES:
            break
        snippets[rel_path] = numbered
        total += len(numbered)

    return snippets


def build_prompt(cluster: dict[str, Any], snippets: dict[str, str]) -> str:
    """Prompt asking for exactly two fenced blocks: analysis and a unified diff."""
    facts = [
        f"kind: {cluster.get('kind')}",
        f"exception: {cluster.get('exc_type') or 'n/a'}",
        f"message class: {cluster.get('message_class') or 'unmatched'}",
        f"operation: {cluster.get('op') or 'n/a'}",
        f"occurrences: {cluster.get('count')}",
        f"versions: {json.dumps(cluster.get('versions', {}))}",
        f"detail: {json.dumps(cluster.get('sample_detail', {}))}",
        f"frames (most recent last): {' -> '.join(cluster.get('frames', []))}",
    ]
    source_blocks = "\n\n".join(
        f"FILE: {path}\n```python\n{body}\n```" for path, body in snippets.items()
    ) or "(no source context available)"

    return (
        "You are improving JSAT, a Python codebase-intelligence tool, using a "
        "defect report collected from a real user's machine.\n\n"
        "The report contains ONLY JSAT-internal facts — the user's own code was "
        "deliberately excluded, so do not speculate about their project.\n\n"
        "DEFECT REPORT:\n" + "\n".join(f"- {f}" for f in facts) + "\n\n"
        f"JSAT SOURCE (line numbers in the left column):\n{source_blocks}\n\n"
        "Produce EXACTLY two fenced blocks and nothing else:\n\n"
        "```analysis\n"
        "<root cause in 2-5 sentences, then the fix you chose and why>\n"
        "```\n\n"
        "```diff\n"
        "<a unified diff with 3 lines of context>\n"
        "```\n\n"
        "Diff rules (violating any of these makes the patch unusable):\n"
        "- Paths must be relative and start with `jsat/` (e.g. `--- a/jsat/tools/x.py`).\n"
        "- Modify existing files only — no new files, no deletions.\n"
        "- Context lines must match the source above EXACTLY, including indentation.\n"
        "- Keep the change minimal and focused on this one defect.\n"
        "- Preserve the surrounding code style.\n"
    )


def extract_blocks(response: str) -> tuple[str, str]:
    """Pull the ```analysis and ```diff blocks out of a model response."""
    def _block(tag: str) -> str:
        marker = f"```{tag}"
        if marker not in response:
            return ""
        body = response.split(marker, 1)[1]
        return body.split("```", 1)[0].strip("\n")

    analysis = _block("analysis")
    diff = _block("diff") or _block("patch")
    return analysis, diff


# ── bundle ────────────────────────────────────────────────────────────────────

def _file_hashes(paths: list[str]) -> list[dict[str, Any]]:
    """Pre-patch sha256 of each touched file, so the maintainer can detect drift."""
    root = jsat_root()
    out = []
    for rel_path in paths:
        rel = rel_path[len("jsat/"):] if rel_path.startswith("jsat/") else rel_path
        path = root / rel
        if not path.exists():
            continue
        data = path.read_bytes()
        out.append({
            "path": rel_path,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        })
    return out


def write_bundle(
    cluster: dict[str, Any], analysis: str, diff: str,
    patch_status: str, changed: list[str], *,
    provider: str = "unknown", model: str = "unknown",
) -> Path:
    """Write an inert improvement bundle. Returns the bundle directory."""
    import jsat

    bundle_id = f"{cluster['fingerprint'][:8]}-{time_now_iso().replace(':', '').replace('-', '')}"
    out = bundles_dir() / bundle_id

    manifest = {
        "schema_version": 1,
        "bundle_id": bundle_id,
        "created_at": time_now_iso(),
        "jsat_version": getattr(jsat, "__version__", "unknown"),
        "install_kind": install_kind(),
        "provider": provider,
        "model": model,
        "cluster": cluster,
        "files": _file_hashes(changed),
        "patch_status": patch_status,
        "sanitizer": {
            "dropped_count": read_state().get("dropped_count", 0),
            "rules_version": 1,
        },
    }

    issue = render_issue(cluster, analysis, manifest)

    # The AI's output is untrusted: re-run the privacy verifier over every file.
    for name, content in (
        ("manifest.json", json.dumps(manifest, indent=2, sort_keys=True)),
        ("analysis.md", analysis or "(no analysis produced)"),
        ("patch.diff", diff or ""),
        ("issue.md", issue),
    ):
        if content and not verify_clean(content):
            content = f"(withheld: {name} did not pass the privacy filter)"
            log.warning("improve_bundle_file_withheld", file=name)
        _safe_write(out / name, content)

    prune_bundles()
    log.info("improve_bundle_written", bundle=str(out), status=patch_status)
    return out


def render_issue(cluster: dict[str, Any], analysis: str, manifest: dict[str, Any]) -> str:
    """Markdown body for the pre-filled GitHub issue."""
    frames = "\n".join(f"  {f}" for f in cluster.get("frames", [])) or "  (none)"
    return (
        f"### What JSAT recorded\n\n"
        f"| field | value |\n|---|---|\n"
        f"| kind | `{cluster.get('kind')}` |\n"
        f"| exception | `{cluster.get('exc_type') or 'n/a'}` |\n"
        f"| message class | `{cluster.get('message_class') or 'unmatched'}` |\n"
        f"| operation | `{cluster.get('op') or 'n/a'}` |\n"
        f"| occurrences | {cluster.get('count')} |\n"
        f"| versions | `{json.dumps(cluster.get('versions', {}))}` |\n"
        f"| patch status | `{manifest.get('patch_status')}` |\n\n"
        f"**Frames**\n```\n{frames}\n```\n\n"
        f"### Analysis\n\n{analysis or '_No analysis produced._'}\n\n"
        f"---\n"
        f"_Generated by `jsat improve` on JSAT {manifest.get('jsat_version')} "
        f"({manifest.get('install_kind')}). Only JSAT-internal data is included — "
        f"no code, paths, or identifiers from the reporter's project._\n"
    )


def issue_url(repo: str, cluster: dict[str, Any], body: str) -> str:
    """Pre-filled GitHub issue URL, truncated to stay under proxy limits."""
    label = cluster.get("exc_type") or cluster.get("kind") or "issue"
    where = cluster.get("op") or (cluster.get("frames") or ["jsat"])[-1]
    title = f"[improve] {label} in {where} (x{cluster.get('count', 1)})"
    base = f"https://github.com/{repo}/issues/new"

    for limit in (len(body), 4000, 2000, 800):
        query = urllib.parse.urlencode({
            "title": title, "labels": "self-improvement", "body": body[:limit],
        })
        url = f"{base}?{query}"
        if len(url) <= _MAX_URL:
            return url
    return f"{base}?{urllib.parse.urlencode({'title': title})}"


def mark_reported(fingerprint: str, bundle_id: str) -> None:
    """Flag a cluster as handled so it stops triggering nudges."""
    clusters = read_clusters()
    if fingerprint in clusters:
        clusters[fingerprint]["reported"] = True
        clusters[fingerprint]["bundle_id"] = bundle_id
        write_clusters(clusters)


def diagnose(cluster: dict[str, Any], ai: Any) -> tuple[str, str, str, list[str]]:
    """Ask the AI for an analysis + patch and validate it.

    Returns ``(analysis, diff, patch_status, changed_paths)``. Never raises: an
    unavailable or misbehaving provider degrades to a diagnosis-only bundle.
    """
    snippets = gather_context(cluster)

    available = False
    try:
        available = bool(ai) and ai.is_available()
    except Exception:
        available = False
    if not available:
        return "", "", "no_ai", []

    try:
        # NoOpProvider.complete() raises, so this must stay guarded.
        response = ai.complete(build_prompt(cluster, snippets), max_tokens=2000)
    except Exception as e:
        log.warning("improve_ai_failed", error=str(e))
        return "", "", "ai_error", []

    analysis, diff = extract_blocks(response)
    if not diff:
        return analysis or response[:2000], "", "no_patch", []

    ok, message, changed = validate_patch(diff, jsat_root())
    if not ok:
        log.info("improve_patch_rejected", reason=message)
        return analysis, diff, "did_not_apply", []
    return analysis, diff, "validated", changed
