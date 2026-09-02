"""
Phase B/D — the indexing pipeline against the real fixture repo.

Asserts against ground truth the fixture guarantees (see fixtures.py):
all six parsers produce symbols, the documented edge types appear, the
incremental path really skips unchanged files, and an export can be
re-imported with the same node count.
"""
from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

from ..core import FAIL, PASS, UNAVAILABLE, Check, Report, run_cli, timed
from ..fixtures import scratch_facts

FACTS = scratch_facts()


def _graph_db(env: dict[str, str]) -> Path | None:
    db = Path(env["JSAT_DATA_DIR"]) / "graph" / "graph.db"
    return db if db.exists() else None


def _read_graph(env: dict[str, str]) -> tuple[dict[str, int], dict[str, int],
                                              set[str], list[str]]:
    """Return (labels, edge_types, languages, node_ids) from the real db."""
    db = _graph_db(env)
    if not db:
        return {}, {}, set(), []
    c = sqlite3.connect(str(db))
    try:
        labels: dict[str, int] = {}
        for (lab,) in c.execute("SELECT label FROM nodes"):
            labels[lab] = labels.get(lab, 0) + 1
        edges: dict[str, int] = {}
        for (t,) in c.execute("SELECT type FROM edges"):
            edges[t] = edges.get(t, 0) + 1
        langs = set()
        for (props,) in c.execute("SELECT properties FROM nodes WHERE label='File'"):
            try:
                lang = json.loads(props).get("language")
            except Exception:
                lang = None
            if lang:
                langs.add(lang)
        ids = [r[0] for r in c.execute("SELECT id FROM nodes")]
        return labels, edges, langs, ids
    finally:
        c.close()


@timed
def check_full_index(jsat_bin: str, env: dict[str, str], repo: Path) -> Check:
    r = run_cli(jsat_bin, ["index", str(repo), "--force"], env, timeout=180)
    if r.returncode != 0:
        return Check("index_full", "index", FAIL,
                     "jsat index --force failed on the fixture repo",
                     detail=f"rc={r.returncode} {r.stderr[:400]}")
    labels, _, _, _ = _read_graph(env)
    if not labels:
        return Check("index_full", "index", FAIL,
                     "index reported success but wrote no nodes",
                     detail=r.stdout[:300])
    return Check("index_full", "index", PASS,
                 f"indexed the fixture repo: "
                 f"{sum(labels.values())} nodes {dict(labels)}",
                 detail=r.stdout.strip()[:300])


@timed
def check_all_parsers_ran(env: dict[str, str]) -> Check:
    """All six languages the README advertises must produce File nodes."""
    _, _, langs, _ = _read_graph(env)
    expected = FACTS["languages"] | {"typescript"}
    missing = sorted(expected - langs)
    if missing:
        return Check("index_all_parsers", "index", FAIL,
                     f"{len(missing)} advertised language(s) produced no nodes: "
                     f"{missing}",
                     detail=f"indexed={sorted(langs)}",
                     remediation="check indexer.languages in the default config "
                                 "and that the tree-sitter grammar is installed")
    return Check("index_all_parsers", "index", PASS,
                 f"all advertised languages parsed: {sorted(langs)}")


@timed
def check_symbols_and_edges(env: dict[str, str]) -> Check:
    """Known-true facts about the fixture: specific symbols and edge types."""
    labels, edges, _, ids = _read_graph(env)
    problems = []
    for fn in FACTS["functions_present"]:
        if not any(i.endswith(f"::{fn}") or f"::{fn}" in i for i in ids):
            problems.append(f"missing Function {fn}")
    for cl in FACTS["classes_present"]:
        if not any(f"::{cl}" in i for i in ids):
            problems.append(f"missing Class {cl}")
    for et in ("CALLS", "IMPORTS", "INHERITS"):
        if edges.get(et, 0) == 0:
            problems.append(f"no {et} edges")
    if problems:
        return Check("index_symbols_edges", "index", FAIL,
                     f"{len(problems)} expected graph fact(s) missing",
                     detail="; ".join(problems[:10]) + f" | edges={dict(edges)}")
    return Check("index_symbols_edges", "index", PASS,
                 f"expected symbols present; edge types {sorted(edges)}",
                 detail=f"{dict(edges)}")


@timed
def check_incremental_skips(jsat_bin: str, env: dict[str, str],
                            repo: Path) -> Check:
    """A second index with nothing changed must skip, not re-parse."""
    r = run_cli(jsat_bin, ["index", str(repo)], env, timeout=180)
    if r.returncode != 0:
        return Check("index_incremental", "index", FAIL,
                     "the incremental re-index failed",
                     detail=f"rc={r.returncode} {r.stderr[:300]}")
    manifest = Path(env["JSAT_DATA_DIR"]) / "index-manifest.json"
    if not manifest.exists():
        return Check("index_incremental", "index", FAIL,
                     "no index-manifest.json was written, so incremental "
                     "indexing cannot work",
                     detail=r.stdout[:300])
    data = json.loads(manifest.read_text())
    tracked = len(data.get("files", {}))
    out = (r.stdout + r.stderr).lower()
    skipped = "skip" in out or "unchanged" in out or "0 files" in out
    if not skipped:
        return Check("index_incremental", "index", FAIL,
                     "a no-change re-index did not report skipping anything",
                     detail=r.stdout[:400],
                     remediation="check manifest.compute_delta's mtime/sha256 path")
    return Check("index_incremental", "index", PASS,
                 f"no-change re-index skipped unchanged files "
                 f"({tracked} files tracked in the manifest)",
                 detail=r.stdout.strip()[:250])


@timed
def check_incremental_picks_up_change(jsat_bin: str, env: dict[str, str],
                                      repo: Path) -> Check:
    """Editing one file must add its new symbol on the next index."""
    target = repo / "svc_users" / "users.py"
    target.write_text(target.read_text() +
                      "\n\ndef selftest_marker_function():\n    return 42\n")
    r = run_cli(jsat_bin, ["index", str(repo)], env, timeout=180)
    _, _, _, ids = _read_graph(env)
    if not any("selftest_marker_function" in i for i in ids):
        return Check("index_incremental_change", "index", FAIL,
                     "a newly added function did not appear after re-indexing",
                     detail=f"rc={r.returncode} {r.stdout[:300]}",
                     remediation="the manifest delta may be treating the file "
                                 "as unchanged")
    return Check("index_incremental_change", "index", PASS,
                 "an edited file's new symbol was picked up incrementally")


@timed
def check_index_md_written(jsat_bin: str, env: dict[str, str]) -> Check:
    md = Path(env["JSAT_DATA_DIR"]) / "INDEX.md"
    if not md.exists():
        return Check("index_md_written", "index", FAIL,
                     "INDEX.md was not generated alongside the graph")
    text = md.read_text()
    for section in ("## Overview", "Language Breakdown"):
        if section not in text:
            return Check("index_md_written", "index", FAIL,
                         f"INDEX.md is missing the '{section}' section",
                         detail=text[:300])
    return Check("index_md_written", "index", PASS,
                 f"INDEX.md generated ({len(text)} bytes) with the expected sections")


@timed
def check_export_import_roundtrip(jsat_bin: str, env: dict[str, str],
                                   repo: Path, tmp: Path) -> Check:
    """Export, verify the archive, import into a fresh data dir, compare counts."""
    archive = tmp / "roundtrip.jsat.zip"
    ex = run_cli(jsat_bin, ["export", str(archive)], env, cwd=str(repo), timeout=120)
    if ex.returncode != 0 or not archive.exists():
        return Check("index_export_import", "index", FAIL,
                     "jsat export did not produce an archive",
                     detail=f"rc={ex.returncode} {ex.stderr[:300]}")
    try:
        with zipfile.ZipFile(archive) as z:
            names = z.namelist()
    except Exception as e:
        return Check("index_export_import", "index", FAIL,
                     f"the exported archive is not a readable zip: {e}")

    before, _, _, ids_before = _read_graph(env)
    fresh = tmp / "import-data"
    imported_env = {**env, "JSAT_DATA_DIR": str(fresh)}
    im = run_cli(jsat_bin, ["import", str(archive)], imported_env,
                 cwd=str(repo), timeout=120)
    if im.returncode != 0:
        return Check("index_export_import", "index", FAIL,
                     "jsat import failed on an archive jsat had just written",
                     detail=f"rc={im.returncode} {im.stderr[:400]}")
    after, _, _, ids_after = _read_graph(imported_env)
    if sum(after.values()) != sum(before.values()):
        return Check("index_export_import", "index", FAIL,
                     f"node count changed across the round trip: "
                     f"{sum(before.values())} → {sum(after.values())}",
                     detail=f"before={before} after={after}")
    return Check("index_export_import", "index", PASS,
                 f"export→import preserved all {sum(after.values())} nodes",
                 detail=f"archive members: {names[:8]}")


@timed
def check_export_rejects_zip_slip(tmp: Path) -> Check:
    """A malicious archive must not write outside the target directory."""
    try:
        from jsat.tools.export import ExportTool
    except Exception as e:
        return Check("export_zip_slip_guard", "security", UNAVAILABLE,
                     f"could not import ExportTool: {e}")
    evil = tmp / "evil.jsat.zip"
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("manifest.json", json.dumps({"version": 1}))
        z.writestr("../../escaped.txt", "should never be written")
    target = tmp / "slip-target"
    target.mkdir(exist_ok=True)
    escaped = tmp.parent / "escaped.txt"
    try:
        escaped.unlink(missing_ok=True)
    except Exception:
        pass
    try:
        ExportTool._safe_extract_target  # noqa: B018
    except AttributeError:
        return Check("export_zip_slip_guard", "security", UNAVAILABLE,
                     "ExportTool has no _safe_extract_target to exercise")
    with zipfile.ZipFile(evil) as z:
        blocked = 0
        for member in z.namelist():
            try:
                ExportTool._safe_extract_target(target, member)  # type: ignore[attr-defined]
            except Exception:
                blocked += 1
    if blocked == 0:
        return Check("export_zip_slip_guard", "security", FAIL,
                     "a ../ archive member was NOT rejected by the extract guard",
                     remediation="check _safe_extract_target in jsat/tools/export.py")
    return Check("export_zip_slip_guard", "security", PASS,
                 f"the extract guard rejected {blocked} path-traversal member(s)")


@timed
def check_export_is_complete_in_process(repo: Path, tmp: Path,
                                        env: dict[str, str]) -> Check:
    """Export in the SAME process that just indexed, then count the archive.

    The CLI round-trip above cannot catch this: each `jsat` invocation is its
    own process, and closing the connection on exit checkpoints the WAL for
    free. The SDK and the export_index MCP tool both export from a live
    process, where committed rows are still in the `-wal` sidecar — so the
    archive was a valid, readable, EMPTY database whose manifest reported the
    correct count.
    """
    import os
    import sqlite3
    import zipfile as _zip

    prior = {k: os.environ.get(k) for k in
             ("JSAT_DATA_DIR", "JSAT_IMPROVE_DIR", "JSAT_SESSIONS_DIR")}
    try:
        os.environ["JSAT_DATA_DIR"] = str(tmp / "inproc-export-data")
        os.environ["JSAT_IMPROVE_DIR"] = str(tmp / "inproc-export-improve")
        os.environ["JSAT_SESSIONS_DIR"] = str(tmp / "inproc-export-sessions")
        from jsat import JSAT
        js = JSAT(repo=str(repo))
        js.index(force=True)
        expected = js.index_status["nodes"]
        if expected <= 0:
            return Check("index_export_complete", "index", FAIL,
                         "the in-process index produced no nodes to export")
        archive = tmp / "inproc.jsat.zip"
        js.export(output=archive)
        with _zip.ZipFile(archive) as z:
            if "graph/graph.db" not in z.namelist():
                return Check("index_export_complete", "index", FAIL,
                             "the archive contains no graph/graph.db",
                             detail=str(z.namelist()))
            extracted = tmp / "inproc-extracted.db"
            extracted.write_bytes(z.read("graph/graph.db"))
            manifest = json.loads(z.read("manifest.json"))
        conn = sqlite3.connect(str(extracted))
        try:
            in_archive = next(conn.execute("SELECT count(*) FROM nodes"))[0]
        finally:
            conn.close()
        if in_archive != expected:
            return Check("index_export_complete", "index", FAIL,
                         f"the exported archive holds {in_archive} nodes but "
                         f"the live graph had {expected} — the backup is "
                         "incomplete while its manifest claims "
                         f"{manifest.get('nodes')}",
                         remediation="checkpoint the WAL before copying the "
                                     "database file (ExportTool.export)")
        return Check("index_export_complete", "index", PASS,
                     f"an in-process export captured all {in_archive} nodes "
                     f"(manifest agrees: {manifest.get('nodes')})")
    finally:
        for k, v in prior.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def run(report: Report, jsat_bin: str, repo: Path, tmp: Path,
        env: dict[str, str]) -> None:
    report.add(check_full_index(jsat_bin, env, repo))
    report.add(check_all_parsers_ran(env))
    report.add(check_symbols_and_edges(env))
    report.add(check_index_md_written(jsat_bin, env))
    report.add(check_incremental_skips(jsat_bin, env, repo))
    report.add(check_incremental_picks_up_change(jsat_bin, env, repo))
    report.add(check_export_import_roundtrip(jsat_bin, env, repo, tmp))
    report.add(check_export_is_complete_in_process(repo, tmp, env))
    report.add(check_export_rejects_zip_slip(tmp))
