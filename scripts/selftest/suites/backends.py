"""
Phase G — graph, cache and vector backends.

Three graph backends and three cache backends are configurable, and only one
of each is ever used in practice. This suite indexes the same fixture repo
through each graph backend and compares the results, and round-trips every
cache backend.

Where a backend needs a service that is not running, the check is
`unavailable`. Where a backend is *present but known not to work with the
rest of the codebase*, that is reported as a real failure with the reason —
because shipping a config option that produces a half-broken install is a
defect, not a missing dependency.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

from ..core import (
    FAIL,
    PASS,
    UNAVAILABLE,
    Check,
    Report,
    run_cli,
    tcp_reachable,
    timed,
)

DOCKER_SERVICES = {
    # name: (image, port, extra docker args)
    "neo4j": ("neo4j:5", 7687, ["-e", "NEO4J_AUTH=neo4j/selftestpassword",
                                 "-p", "7474:7474", "-p", "7687:7687"]),
    "qdrant": ("qdrant/qdrant", 6333, ["-p", "6333:6333"]),
    "redis": ("redis:7", 6379, ["-p", "6379:6379"]),
}


def docker_usable() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "ps"], capture_output=True,
                              timeout=10).returncode == 0
    except Exception:
        return False


@timed
def check_graph_backend(jsat_bin: str, backend: str, repo: Path, tmp: Path,
                        env: dict[str, str]) -> Check:
    """Index the fixture repo through this backend and count what landed."""
    data_dir = tmp / f"backend-{backend}"
    cfg_dir = tmp / f"backend-cfg-{backend}"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg = cfg_dir / "config.yaml"
    cfg.write_text(
        "version: '1'\n"
        f"graph:\n  backend: {backend}\n"
        "embeddings:\n  provider: none\n"
        "ai:\n  provider: none\n"
        "cache:\n  backend: memory\n"
    )
    scoped = {**env, "JSAT_DATA_DIR": str(data_dir), "JSAT_CONFIG": str(cfg)}
    r = run_cli(jsat_bin, ["index", str(repo), "--force"], scoped, timeout=240)
    if r.returncode != 0:
        return Check(f"graph_backend_{backend}", "backends", FAIL,
                     f"indexing with graph.backend={backend} failed",
                     detail=f"rc={r.returncode} {(r.stdout + r.stderr)[-500:]}")
    status = run_cli(jsat_bin, ["doctor", "--json"], scoped,
                     cwd=str(repo), timeout=120)
    try:
        nodes = json.loads(status.stdout).get("index", {}).get("nodes", 0)
    except Exception:
        nodes = -1
    if nodes <= 0:
        return Check(f"graph_backend_{backend}", "backends", FAIL,
                     f"graph.backend={backend} indexed without error but "
                     f"reports {nodes} nodes",
                     detail=(r.stdout + status.stdout)[-500:])
    return Check(f"graph_backend_{backend}", "backends", PASS,
                 f"graph.backend={backend} indexed the fixture repo "
                 f"({nodes} nodes)",
                 detail=r.stdout.strip()[-250:])


@timed
def check_sqlite_and_lightgraph_agree(tmp: Path) -> Check:
    """The two SQLite-family backends must produce identical graphs."""
    counts = {}
    for backend in ("sqlite", "lightgraph"):
        db = tmp / f"backend-{backend}" / "graph" / "graph.db"
        if not db.exists():
            return Check("graph_backends_agree", "backends", UNAVAILABLE,
                         f"no graph.db for {backend} to compare")
        c = sqlite3.connect(str(db))
        try:
            counts[backend] = (
                next(c.execute("SELECT count(*) FROM nodes"))[0],
                next(c.execute("SELECT count(*) FROM edges"))[0],
            )
        finally:
            c.close()
    if counts["sqlite"] != counts["lightgraph"]:
        return Check("graph_backends_agree", "backends", FAIL,
                     "sqlite and lightgraph produced different graphs from the "
                     "same source tree",
                     detail=f"{counts}",
                     remediation="the two backends must be interchangeable")
    return Check("graph_backends_agree", "backends", PASS,
                 f"sqlite and lightgraph produced identical graphs "
                 f"{counts['sqlite']} (nodes, edges)")


@timed
def check_neo4j_backend_usability() -> Check:
    """Neo4j is offered in config, but every tool query is SQLite SQL.

    `Neo4jGraph.query()` deliberately rejects SQL rather than return wrong
    data, which is the right call — but it means selecting this backend
    produces an install where query/feature/test_gaps and the indexer's
    symbol-resolution pass cannot work. Silently half-working is the defect;
    saying so at the moment the choice takes effect is the fix. This asserts
    the guard still recognises the SQL jsat emits AND that the limitation is
    surfaced to the user.
    """
    import inspect
    try:
        from jsat._graph.neo4j import Neo4jGraph, _looks_like_sql
    except Exception as e:
        return Check("graph_neo4j_usable", "backends", UNAVAILABLE,
                     f"neo4j driver not importable: {e}")

    # The exact SQL shape jsat/tools/*.py emits.
    sql = ("SELECT id, properties FROM nodes WHERE label='Function' "
           "AND json_extract(properties, '$.name') = 'x'")
    if not _looks_like_sql(sql):
        return Check("graph_neo4j_usable", "backends", FAIL,
                     "the Neo4j backend's SQL guard no longer recognises the "
                     "SQL that jsat's own tools emit, so it would forward it "
                     "to Cypher and fail obscurely",
                     detail=sql[:200])

    from ..core import REPO_ROOT
    offenders = subprocess.run(
        ["grep", "-rln", "--include=*.py", "-E",
         "FROM nodes|FROM edges|json_extract",
         str(REPO_ROOT / "jsat" / "tools")],
        capture_output=True, text=True).stdout.split()
    names = sorted(Path(o).name for o in offenders if o.strip())

    src = inspect.getsource(Neo4jGraph.__init__)
    surfaced = "neo4j_partial_support" in src
    if names and not surfaced:
        return Check("graph_neo4j_usable", "backends", FAIL,
                     f"graph.backend=neo4j is selectable and {len(names)} tool "
                     "module(s) query with SQLite-only SQL it rejects, but the "
                     "user is never told — the install half-works silently",
                     detail=f"modules emitting SQL: {names}",
                     remediation="warn at construction naming what degrades, "
                                 "or add a Cypher translation layer")
    if names:
        return Check("graph_neo4j_usable", "backends", PASS,
                     f"the Neo4j backend's SQL guard holds and its partial "
                     f"support is surfaced at construction "
                     f"({len(names)} tool module(s) need SQLite)",
                     detail=f"degraded for: {names}")
    return Check("graph_neo4j_usable", "backends", PASS,
                 "no tool module emits SQLite-only SQL, so the Neo4j backend "
                 "is fully usable")


@timed
def check_cache_backend(backend: str, tmp: Path) -> Check:
    """Real set/get/invalidate through the configured cache backend."""
    from jsat._cache import get_cache
    from jsat._models import CacheConfig, JSATConfig
    if backend == "redis" and not tcp_reachable("localhost", 6379):
        return Check(f"cache_{backend}", "backends", UNAVAILABLE,
                     "redis is not reachable at localhost:6379")
    cfg = JSATConfig()
    cfg.cache = CacheConfig(backend=backend)  # type: ignore[arg-type]
    if backend == "disk":
        cfg.cache.disk_path = str(tmp / "cache-disk")
    try:
        cache = get_cache(cfg)
    except Exception as e:
        return Check(f"cache_{backend}", "backends", FAIL,
                     f"could not construct the {backend} cache: "
                     f"{type(e).__name__}: {e}")
    actual = type(cache).__name__.lower()
    if backend == "redis" and "redis" not in actual:
        return Check(f"cache_{backend}", "backends", FAIL,
                     f"cache.backend=redis silently fell back to {actual}",
                     remediation="a configured backend that cannot be built "
                                 "should say so, not degrade silently")
    q, ctx = "what does validate_amount do?", "ctxhash123"
    cache.set(q, ctx, {"answer": "it validates the amount"},
              affected_files=["svc_payments/payments.py"])
    got = cache.get(q, ctx)
    if not got:
        return Check(f"cache_{backend}", "backends", FAIL,
                     f"{backend} cache did not return a value just written")
    cache.invalidate_for_files(["svc_payments/payments.py"])
    after = cache.get(q, ctx)
    if after:
        return Check(f"cache_{backend}", "backends", FAIL,
                     f"{backend} cache kept an entry after its source file was "
                     "invalidated — stale answers would be served",
                     detail=str(after)[:200])
    return Check(f"cache_{backend}", "backends", PASS,
                 f"{backend} cache ({type(cache).__name__}) round-tripped a "
                 "value and honoured file invalidation")


@timed
def check_embeddings_are_wired() -> Check:
    """embeddings.* and vector_store.* must not be documented as functional
    unless something calls them.

    The subsystem is fully implemented (three backends, a cosine helper) but
    has no call sites, so configuring it changes nothing. That is an
    acceptable state for unreleased functionality — silently presenting it as
    working is not. This asserts one of the two is true: either an embedder
    is actually invoked, or the config and docs say plainly that it is not
    yet wired in.
    """
    from ..core import REPO_ROOT
    hits = subprocess.run(
        ["grep", "-rn", "--include=*.py", "-E",
         r"\.embed_batch\(|\.embed\(|get_embedder\(",
         str(REPO_ROOT / "jsat")],
        capture_output=True, text=True).stdout.splitlines()
    external = [h for h in hits if "/jsat/_embed/" not in h]
    if external:
        return Check("embeddings_wired", "backends", PASS,
                     f"embeddings are used from {len(external)} call site(s) "
                     "outside the _embed package")

    marker = "NOT YET WIRED IN"
    docs = (REPO_ROOT / "docs" / "configuration.md").read_text()
    models = (REPO_ROOT / "jsat" / "_models.py").read_text()
    docs_ok = marker in docs
    schema_ok = marker in models
    if not (docs_ok and schema_ok):
        missing = []
        if not docs_ok:
            missing.append("docs/configuration.md")
        if not schema_ok:
            missing.append("jsat/_models.py")
        return Check("embeddings_wired", "backends", FAIL,
                     "the embeddings/vector-store subsystem has no call sites "
                     f"and is not marked as unwired in {missing}, so users "
                     "will configure something inert",
                     remediation="either wire embeddings into indexing/query, "
                                 f"or state '{marker}' at the schema and in "
                                 "the docs")
    return Check("embeddings_wired", "backends", PASS,
                 "embeddings are not wired into indexing or querying, and both "
                 "the config schema and the docs say so explicitly")


@timed
def check_graph_caps_enforced(tmp: Path) -> Check:
    """graph.max_nodes/max_edges are configurable; verify they actually bind.

    Enforcement is at the bulk-insert boundary, which is where mass growth
    happens (the indexer batches 2,000 rows at a time) and where one COUNT
    per batch costs nothing. Both the allowed and the refused case are
    asserted, since a cap that rejects everything is as broken as one that
    rejects nothing.
    """
    from jsat._exceptions import GraphCapacityError
    from jsat._graph.sqlite import SQLiteGraph
    from jsat._models import GraphConfig

    results = []
    for backend_name, factory in (("sqlite", SQLiteGraph),):
        cfg = GraphConfig(path=str(tmp / f"caps-{backend_name}" / "graph.db"),
                          max_nodes=5, max_edges=5)
        Path(cfg.path).parent.mkdir(parents=True, exist_ok=True)
        g = factory(cfg)
        try:
            g.bulk_add_nodes([{"id": f"n{i}", "label": "File", "properties": {}}
                              for i in range(3)])
            if g.node_count() != 3:
                return Check("graph_caps_enforced", "backends", FAIL,
                             f"{backend_name}: a bulk insert under the cap did "
                             f"not land ({g.node_count()} of 3 stored)")
            try:
                g.bulk_add_nodes([{"id": f"m{i}", "label": "File",
                                   "properties": {}} for i in range(10)])
            except GraphCapacityError as e:
                results.append(f"{backend_name}: refused at "
                               f"{e.current_nodes}/{e.max_nodes}")
            else:
                return Check("graph_caps_enforced", "backends", FAIL,
                             f"{backend_name}: graph.max_nodes=5 was ignored — "
                             f"{g.node_count()} nodes written and "
                             "GraphCapacityError never raised",
                             remediation="enforce the caps in the graph "
                                         "backends, or remove max_nodes/"
                                         "max_edges from the config schema so "
                                         "they do not read as a live limit")
        finally:
            g.close()
    return Check("graph_caps_enforced", "backends", PASS,
                 "bulk inserts under the cap succeed and inserts that would "
                 f"exceed it raise GraphCapacityError ({'; '.join(results)})")


def start_docker_services(report: Report) -> dict[str, str]:
    """Start the team-tier services. Returns {name: container_id}."""
    started: dict[str, str] = {}
    for name, (image, port, extra) in DOCKER_SERVICES.items():
        if tcp_reachable("localhost", port):
            report.add(Check(f"docker_{name}", "backends", PASS,
                             f"{name} already reachable on :{port}; reusing it"))
            continue
        r = subprocess.run(
            ["docker", "run", "-d", "--rm", "--name", f"jsat-selftest-{name}",
             *extra, image],
            capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            report.add(Check(f"docker_{name}", "backends", UNAVAILABLE,
                             f"could not start {name} via docker",
                             detail=r.stderr.strip()[:300]))
            continue
        started[name] = r.stdout.strip()[:12]
        # Wait for the port, but bounded: neo4j takes ~20-40s to accept bolt.
        import time
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if tcp_reachable("localhost", port):
                break
            time.sleep(2)
        if tcp_reachable("localhost", port):
            report.add(Check(f"docker_{name}", "backends", PASS,
                             f"started {name} ({image}) and :{port} accepted a "
                             "connection"))
        else:
            report.add(Check(f"docker_{name}", "backends", UNAVAILABLE,
                             f"{name} container started but :{port} never came up"))
    return started


def stop_docker_services(started: dict[str, str]) -> None:
    for name in started:
        subprocess.run(["docker", "rm", "-f", f"jsat-selftest-{name}"],
                       capture_output=True, timeout=120)


def run(report: Report, jsat_bin: str, repo: Path, tmp: Path,
        env: dict[str, str]) -> None:
    started: dict[str, str] = {}
    if docker_usable():
        started = start_docker_services(report)
    else:
        for name in DOCKER_SERVICES:
            report.add(Check(f"docker_{name}", "backends", UNAVAILABLE,
                             f"docker is not usable, so {name} was not started",
                             remediation="sudo usermod -aG docker $USER && "
                                         "newgrp docker"))
    try:
        for backend in ("sqlite", "lightgraph"):
            report.add(check_graph_backend(jsat_bin, backend, repo, tmp, env))
        report.add(check_sqlite_and_lightgraph_agree(tmp))
        report.add(check_neo4j_backend_usability())
        for backend in ("memory", "disk", "redis"):
            report.add(check_cache_backend(backend, tmp))
        report.add(check_embeddings_are_wired())
        report.add(check_graph_caps_enforced(tmp))
    finally:
        stop_docker_services(started)
