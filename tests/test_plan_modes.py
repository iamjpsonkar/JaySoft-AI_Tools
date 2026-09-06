"""Tests for the universal `_mode` execution modes (plan / beast) and the
`jsat plan` CLI group.

plan  → the call is intercepted, persisted as a proposal (`status=proposed`),
        and NOTHING executes. Approval happens via `execute_plan` (MCP) or the
        `jsat plan` CLI. beast → the soft budget and depth cap are scaled up and
        the result is tagged `_beast`/`elapsed_s`/`tool`.
"""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from jsat.cli import app
from jsat.mcp.server import _ROLE_PERMISSIONS, MCPServer

runner = CliRunner()


MARK = pytest.mark.ci


def _make_server(env: dict[str, str] | None = None) -> MCPServer:
    """Build an MCPServer with a minimal JSAT mock and optional env overrides."""
    jsat = MagicMock()
    jsat._cfg.graph.backend = "sqlite"
    jsat._cfg.ai.provider = "anthropic"
    jsat._cfg.ai.model = "claude-3-haiku"
    jsat.index_status = {"nodes": 0, "edges": 0}
    jsat._get_graph.return_value = MagicMock()

    env_patch = {
        "JSAT_MCP_TOKEN": "",
        "JSAT_MCP_TOKEN_ROLES": "",
        "JSAT_MCP_ALLOW_INSECURE": "",
        **(env or {}),
    }
    with patch.dict(os.environ, env_patch, clear=False):
        for k, v in env_patch.items():
            if not v and k in os.environ:
                del os.environ[k]
        server = MCPServer(jsat)
    return server


def _call(server: MCPServer, tool: str, args: dict | None = None,
          mode: str | None = None, session: str | None = None) -> dict:
    """Drive the real tools/call path with the universal params injected."""
    arguments = dict(args or {})
    if mode:
        arguments["_mode"] = mode
    if session:
        arguments["_dashboard_session"] = session
    msg = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments, "_auth_token": ""},
    }
    return server._handle(msg) or {}  # type: ignore[return-value]


def _payload(resp: dict) -> dict:
    """Parse the text content of a successful result back into an object."""
    assert "result" in resp, f"expected a result, got: {resp}"
    return json.loads(resp["result"]["content"][0]["text"])


@MARK
def test_plan_mode_persists_proposal_and_executes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("JSAT_SESSIONS_DIR", str(tmp_path / "sessions"))
    server = _make_server()

    resp = _call(server, "get_metrics", mode="plan", session="demo")

    plan = _payload(resp)
    assert plan["_mode"] == "plan"
    assert plan["nothing_executed"] is True
    assert plan["status"] == "proposed"
    assert plan["plan_id"].startswith("plan-demo")
    assert plan["steps"] == [{
        "step": 1, "tool": "get_metrics", "args": {},
        "kind": "read_or_compute", "done": False,
    }]
    # The step is still `done: False` and only the plan-intercept metric was
    # recorded (0.0 elapsed) — the actual tool handler never ran.
    assert server._metrics.get("get_metrics") == {"calls": 1, "total_ms": 0.0, "errors": 0}


@MARK
def test_plan_mode_dedupes_identical_probes(tmp_path, monkeypatch):
    monkeypatch.setenv("JSAT_SESSIONS_DIR", str(tmp_path / "sessions"))
    server = _make_server()

    first = _payload(_call(server, "get_metrics", mode="plan", session="demo"))
    second = _payload(_call(server, "get_metrics", mode="plan", session="demo"))

    assert first["plan_id"] == second["plan_id"]
    assert len(second["steps"]) == 1  # appended, not duplicated


@MARK
def test_execute_plan_completes_stored_proposal(tmp_path, monkeypatch):
    monkeypatch.setenv("JSAT_SESSIONS_DIR", str(tmp_path / "sessions"))
    server = _make_server()
    proposed = _payload(_call(server, "get_metrics", mode="plan", session="demo"))

    resp = _call(server, "execute_plan", {"plan_id": proposed["plan_id"]})
    outcome = _payload(resp)
    assert outcome["status"] == "completed"
    assert outcome["steps_run"] == 1
    assert outcome["errors"] == 0
    assert outcome["results"][0]["tool"] == "get_metrics"
    assert outcome["results"][0]["ok"] is True

    # Re-running a completed plan is refused — nothing double-executes.
    rerun = _payload(_call(server, "execute_plan", {"plan_id": proposed["plan_id"]}))
    assert rerun["status"] == "already_completed"

    # The metric WAS recorded once now that it actually ran.
    assert server._metrics["get_metrics"]["calls"] == 1


@MARK
def test_execute_plan_inline_tool_args(tmp_path, monkeypatch):
    monkeypatch.setenv("JSAT_SESSIONS_DIR", str(tmp_path / "sessions"))
    server = _make_server()

    outcome = _payload(_call(server, "execute_plan", {"tool": "get_metrics"}))

    assert outcome["status"] == "completed"
    assert outcome["steps_run"] == 1
    assert outcome["results"][0]["tool"] == "get_metrics"


@MARK
def test_execute_plan_without_match_lists_available_plans(tmp_path, monkeypatch):
    monkeypatch.setenv("JSAT_SESSIONS_DIR", str(tmp_path / "sessions"))
    server = _make_server()

    outcome = _payload(_call(server, "execute_plan", {"plan_id": "nope"}))

    assert "error" in outcome
    assert isinstance(outcome.get("plans"), list)


@MARK
def test_invalid_mode_is_rejected_with_jsonrpc_error(tmp_path, monkeypatch):
    monkeypatch.setenv("JSAT_SESSIONS_DIR", str(tmp_path / "sessions"))
    server = _make_server()

    resp = _call(server, "get_metrics", mode="bogus")

    assert "error" in resp
    assert resp["error"]["code"] == -32602
    assert resp["error"]["message"] == "Invalid _mode 'bogus': use default | plan | beast"


@MARK
def test_beast_mode_scales_and_tags_the_result(tmp_path, monkeypatch):
    monkeypatch.setenv("JSAT_SESSIONS_DIR", str(tmp_path / "sessions"))
    server = _make_server()

    resp = _call(server, "get_jsat_version", mode="beast")
    result = _payload(resp)

    # `get_jsat_version` returns a JSON string, so beast mode must wrap it in a
    # `payload` envelope and `_handle` must tag `tool`/`elapsed_s` on top.
    assert result["_beast"] is True
    assert result["tool"] == "get_jsat_version"
    assert isinstance(result["elapsed_s"], (int, float))
    inner = json.loads(result["payload"])
    assert inner["version"]
    assert inner["ai_provider"] == "anthropic"


@MARK
def test_beast_mode_tagged_inline_dict_handler(tmp_path, monkeypatch):
    """A dict-returning handler is tagged in place (setdefault) not wrapped."""
    monkeypatch.setenv("JSAT_SESSIONS_DIR", str(tmp_path / "sessions"))
    server = _make_server()
    server._registry["_test_beast_dict"] = {
        "description": "test-only",
        "schema": {"type": "object", "properties": {}},
        "handler": lambda a: {"ok": True},
    }

    resp = _call(server, "_test_beast_dict", mode="beast")
    result = _payload(resp)

    assert result["ok"] is True
    assert result["_beast"] is True
    assert isinstance(result["elapsed_s"], (int, float))
    assert "journey" in result


@MARK
def test_plan_mode_result_is_untouched_by_beast_scaling(tmp_path, monkeypatch):
    monkeypatch.setenv("JSAT_SESSIONS_DIR", str(tmp_path / "sessions"))
    server = _make_server()

    resp = _call(server, "get_jsat_version")
    result = _payload(resp)

    assert result.get("_beast") is None
    assert "tool" not in result
    assert "elapsed_s" not in result
    assert result["version"]


@MARK
def test_execute_plan_is_developer_only_rbac():
    assert "execute_plan" in _ROLE_PERMISSIONS["developer"]
    assert "execute_plan" not in _ROLE_PERMISSIONS["viewer"]


@MARK
def test_cli_plan_lifecycle(tmp_path, monkeypatch):
    """`jsat plan list/show/approve/run` round-trips a seeded plan through the
    real CLI; a completed plan refuses re-runs and a fresh plan can be
    discarded."""
    monkeypatch.setenv("JSAT_SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("JSAT_DATA_DIR", str(tmp_path / "data"))

    from jsat import _planner
    from jsat._sessions import sessions_dir

    _planner.append_step("runme-check", "get_jsat_version", {}, 5.0)
    plan_id = "plan-runme-check"

    listed = runner.invoke(app, ["plan", "list"])
    assert listed.exit_code == 0
    assert plan_id in listed.stdout

    shown = runner.invoke(app, ["plan", "show", plan_id])
    assert shown.exit_code == 0
    assert "proposed" in shown.stdout
    assert "get_jsat_version" in shown.stdout

    approved = runner.invoke(app, ["plan", "approve", plan_id])
    assert approved.exit_code == 0
    assert "Approved" in approved.stdout

    ran = runner.invoke(app, ["plan", "run", plan_id])
    assert ran.exit_code == 0
    assert "1 step(s) executed" in ran.stdout
    assert sessions_dir().joinpath(f"{plan_id}.md").exists()

    rerun = runner.invoke(app, ["plan", "run", plan_id])
    assert rerun.exit_code == 0
    assert "Already completed" in rerun.stdout

    # Discard works on a separate, never-run proposal.
    _planner.append_step("discard-me", "get_index_status", {}, 5.0)
    disc = runner.invoke(app, ["plan", "discard", "plan-discard-me"])
    assert disc.exit_code == 0
    assert "Rejected" in disc.stdout

    # Rejected plans still surface in `list`, but under their own status.
    rejected = runner.invoke(app, ["plan", "list", "--status", "rejected"])
    assert rejected.exit_code == 0
    assert "plan-discard-me" in rejected.stdout
    proposed = runner.invoke(app, ["plan", "list", "--status", "proposed"])
    assert "plan-discard-me" not in proposed.stdout