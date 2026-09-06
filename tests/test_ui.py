"""Tests for jsat.ui — the Studio web app + terminal UI surface.

CI-safe: no network, no external services, no AI calls. Uses a real JSAT
instance (graph pointed at an in-memory LightGraph built by the real
IndexerTool) and the real MCP registry, so a tool behaves here exactly as it
does over MCP.
"""
from __future__ import annotations

import json
import socket
from pathlib import Path
from urllib import request

import pytest

from jsat.ui._intent import resolve

pytestmark = pytest.mark.ci


@pytest.fixture(autouse=True)
def isolate_jsat_data(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("JSAT_DATA_DIR", str(tmp_path / "jsat-data"))
    monkeypatch.setenv("JSAT_SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("JSAT_IMPROVE_DIR", str(tmp_path / "improve"))


@pytest.fixture
def indexed_graph(tmp_path: Path):
    """A real graph indexed from a tiny python repo by IndexerTool."""
    from jsat._graph.sqlite import SQLiteGraph
    from jsat._models import JSATConfig
    from jsat.tools.indexer import IndexerTool

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "payments.py").write_text(
        '"""Payment service."""\n\n'
        "def process(amount: float) -> bool:\n"
        '    """Process a payment."""\n'
        "    return amount > 0\n\n"
        "def refund(order_id: str) -> bool:\n"
        "    return bool(order_id)\n"
    )
    gpath = tmp_path / "graph" / "graph.db"
    g = SQLiteGraph(JSATConfig().graph.model_copy(update={"path": str(gpath)}))
    IndexerTool(graph=g, cfg=JSATConfig(), ai=None).run(repo)
    return g


@pytest.fixture
def api(indexed_graph, tmp_path: Path):
    """StudioAPI over a real JSAT whose graph is our in-memory index."""
    from jsat import JSAT
    from jsat.ui._api import StudioAPI

    js = JSAT(repo=str(tmp_path / "repo"))
    js._graph = indexed_graph  # noqa: SLF001 — point the instance at the in-memory index
    return StudioAPI(js)


# ── intent resolver ─────────────────────────────────────────────────────────

def test_intent_routes_explicit_phrases() -> None:
    cases = {
        "what breaks if I change refund()": "blast_radius",
        "security review of .": "security_review",
        "which functions are untested": "get_test_gaps",
        "investigate why orders are failing": "investigate_incident",
        "add a unit test for process": "generate_unit_test",
        "api diff between main and HEAD": "get_api_diff",
        "who consumes the orders topic": "get_consumers",
        "show data flow for payments": "get_data_flow",
        "estimate lock duration for the users table": "estimate_lock_duration",
        "validate this migration": "validate_migration",
        "find hardcoded secrets": "list_secrets",
        "list dependency cves": "get_dependency_cves",
        "how many tokens is this text": "token_count",
        "token budget for claude-cli": "token_budget",
        "count tokens and compress": "token_count",
        "compress this text": "token_compress",
        "prompt improve this": "prompt_optimize",
        "most reliable bugs found": "get_high_confidence_bugs",
        "review the diff": "submit_for_review",
        "recent changes": "get_recent_changes",
        "is everything healthy": "health",
        "plan out the refactor": "ithinking_plan",
        "improve jsat": "improve_status",
    }
    for text, expected in cases.items():
        intent = resolve(text)
        assert intent.tool == expected, f"{text!r}: got {intent.tool}, want {expected}"


def test_intent_extracts_target() -> None:
    i = resolve("what breaks if I touch transfer_money?")
    assert i.tool == "blast_radius" and i.args.get("target") == "transfer_money"
    j = resolve("trace message flows from start_payment to notify")
    assert j.tool == "trace_call_chain"
    k = resolve("what breaks if I change `parse_orders`?")
    assert k.args.get("target") == "parse_orders"


def test_intent_falls_back_to_query() -> None:
    i = resolve("why is the sky blue today")
    assert i.tool == "query"
    assert i.args.get("question", "").startswith("why is the sky blue")


# ── StudioAPI ───────────────────────────────────────────────────────────────

def test_status_and_index(api) -> None:
    s = api.status()
    assert s["jsat_version"]
    assert isinstance(s["tools"], int) and s["tools"] > 0
    idx = api.index()
    assert set(("nodes", "edges")) <= set(idx)
    assert idx["tools"] == s["tools"]


def test_catalog_lists_tools(api) -> None:
    tools = api.catalog()
    names = {t["name"] for t in tools}
    assert "get_index_status" in names
    for t in tools:
        assert isinstance(t["description"], str)
        assert isinstance(t["properties"], list)
        assert isinstance(t["required"], list)


def test_run_tool_degrades_per_tool(api) -> None:
    ok = api.run_tool("token_count", {"text": "hello world"})
    assert ok["ok"] is True and json.loads(ok["result"])["tokens"] > 0
    missing = api.run_tool("does_not_exist", {})
    assert missing["ok"] is False and "unknown tool" in missing["error"]
    bad = api.run_tool("get_consumers", {"target": 123})
    assert "ok" in bad


def test_prompt_routes_to_real_tool(api) -> None:
    out = api.prompt("what breaks if I change refund()")
    assert out["intent"] == "blast_radius"
    assert "confidence" in out and "reason" in out
    assert out["args"].get("target")
    idea = api.prompt("this is not a real codebase question at all")
    assert idea["intent"] == "query"
    assert idea["args"].get("question")


def test_nodes_from_real_index(api) -> None:
    funcs = api.nodes("function")
    assert funcs["count"] >= 2  # process + refund
    assert any(r.get("name") == "refund" for r in funcs["rows"])
    assert api.nodes("class")["count"] == 0  # none defined, gracefully empty
    unknown = api.nodes("banana")
    assert "error" in unknown


def test_sessions_and_plans_lists(api) -> None:
    assert isinstance(api.sessions(), list)
    assert isinstance(api.plans(), list)


# ── HTTP server ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def server_url(tmp_path_factory):
    import os

    from jsat import JSAT
    from jsat.ui import server as ui_server

    datadir = tmp_path_factory.mktemp("ui-data")
    old = {k: os.environ.get(k) for k in ("JSAT_DATA_DIR", "JSAT_SESSIONS_DIR", "JSAT_IMPROVE_DIR")}
    os.environ["JSAT_DATA_DIR"] = str(datadir / "data")
    os.environ["JSAT_SESSIONS_DIR"] = str(datadir / "sessions")
    os.environ["JSAT_IMPROVE_DIR"] = str(datadir / "improve")
    try:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            free = s.getsockname()[1]
        js = JSAT(repo=".")
        url, _ = ui_server.start_studio(js, port=free, open_browser=False)
        assert url and url.startswith("http://127.0.0.1")
        yield url
    finally:
        ui_server.stop_studio()
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _get(url: str) -> tuple[int, object]:
    try:
        with request.urlopen(url, timeout=10) as r:  # noqa: S310 — localhost test server
            return r.status, json.loads(r.read().decode("utf-8"))
    except request.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


def test_server_serves_shell(server_url) -> None:
    with request.urlopen(server_url + "/studio", timeout=10) as r:  # noqa: S310
        body = r.read().decode("utf-8")
    assert r.status == 200
    assert "JSAT" in body and "jsat-studio" not in body
    assert "<div id=\"palette\"" in body


def test_server_api_endpoints(server_url) -> None:
    status, data = _get(server_url + "/api/status")
    assert status == 200 and data["jsat_version"]
    status, tools = _get(server_url + "/api/tools")
    assert status == 200 and len(tools["tools"]) > 0
    status, bogus = _get(server_url + "/api/nope")
    assert status == 404 and "error" in bogus


def test_server_prompt_post(server_url) -> None:
    body = json.dumps({"text": "count the tokens in this text"}).encode("utf-8")
    req = request.Request(server_url + "/api/prompt", data=body,  # noqa: S310
                          headers={"Content-Type": "application/json"})
    with request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read().decode("utf-8"))
    assert r.status == 200
    assert data["intent"] == "token_count"


def test_server_tool_post(server_url) -> None:
    body = json.dumps({"args": {"text": "hello studio"}}).encode("utf-8")
    req = request.Request(server_url + "/api/tools/token_count", data=body,  # noqa: S310
                          headers={"Content-Type": "application/json"})
    with request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read().decode("utf-8"))
    assert r.status == 200 and data["ok"] is True


def test_server_nodes(server_url) -> None:
    status, data = _get(server_url + "/api/nodes?label=function&limit=5")
    assert status == 200 and set(data) >= {"label", "count", "rows"}