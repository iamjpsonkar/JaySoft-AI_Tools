"""Tests for jsat.mcp.server — RBAC, auth, and fail-closed behaviour."""
from __future__ import annotations

import json
import os
import time
from unittest.mock import MagicMock, patch

import pytest

from jsat.mcp.server import MCPServer, _allowed

# ── Helpers ───────────────────────────────────────────────────────────────────

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
    # Patch os.environ selectively (only keys we care about)
    with patch.dict(os.environ, env_patch, clear=False):
        # Also clear the keys we want absent when their value is ""
        for k, v in env_patch.items():
            if not v and k in os.environ:
                del os.environ[k]
        server = MCPServer(jsat)
    return server


def _tool_call(server: MCPServer, tool_name: str, token: str = "") -> dict:
    msg = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": {}, "_auth_token": token},
    }
    return server._handle(msg) or {}  # type: ignore[return-value]


def _initialize(server: MCPServer) -> dict:
    msg = {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}}
    return server._handle(msg) or {}  # type: ignore[return-value]


@pytest.mark.ci
def test_blast_radius_file_uses_documented_path_argument():
    server = _make_server()
    server._jsat.blast_radius.return_value = {"summary": {}}

    raw = server._registry["blast_radius_file"]["handler"]({"path": "jsat/_core.py"})

    assert json.loads(raw) == {"summary": {}}
    server._jsat.blast_radius.assert_called_once_with(
        target="jsat/_core.py", max_depth=5
    )


@pytest.mark.ci
def test_blast_radius_file_keeps_legacy_file_argument():
    server = _make_server()
    server._jsat.blast_radius.return_value = {"summary": {}}

    server._registry["blast_radius_file"]["handler"]({"file": "legacy.py"})

    server._jsat.blast_radius.assert_called_once_with(target="legacy.py", max_depth=5)


# ── _allowed() — pure function tests ─────────────────────────────────────────

@pytest.mark.ci
def test_allowed_admin_unrestricted():
    assert _allowed("admin", "index_repo") is True
    assert _allowed("admin", "list_secrets") is True
    assert _allowed("admin", "any_unknown_tool") is True


@pytest.mark.ci
def test_allowed_viewer_read_only_tools():
    assert _allowed("viewer", "query") is True
    assert _allowed("viewer", "list_services") is True
    assert _allowed("viewer", "knowledge_query") is True


@pytest.mark.ci
def test_allowed_viewer_blocked_from_write_tools():
    assert _allowed("viewer", "index_repo") is False
    assert _allowed("viewer", "list_secrets") is False
    assert _allowed("viewer", "knowledge_add") is False


@pytest.mark.ci
def test_allowed_developer_includes_security_tools():
    assert _allowed("developer", "security_review") is True
    assert _allowed("developer", "list_secrets") is True
    assert _allowed("developer", "validate_migration") is True
    assert _allowed("developer", "knowledge_add") is True


@pytest.mark.ci
def test_allowed_unknown_role_denies_everything():
    assert _allowed("ghost", "query") is False
    assert _allowed("", "query") is False


# ── Fail-closed: no auth configured ──────────────────────────────────────────

@pytest.mark.ci
def test_no_auth_allows_tool_calls_with_warning():
    """Default state (no env vars set) must allow tool calls — MCP over stdio is local-only."""
    server = _make_server()
    # No auth configured → server warns at startup but does NOT reject calls
    assert not server._auth_token
    assert not server._token_roles
    # The call proceeds past auth (may fail for other reasons, but not with a 401)
    resp = _tool_call(server, "query")
    if "error" in resp:
        assert resp["error"]["code"] != -32600


@pytest.mark.ci
def test_no_auth_tools_list_succeeds():
    """tools/list must succeed when no auth is configured."""
    server = _make_server()
    msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    resp = server._handle(msg)
    assert resp is not None and "result" in resp


@pytest.mark.ci
def test_no_auth_initialize_handshake_succeeds():
    """initialize must succeed even when no auth is configured (MCP handshake)."""
    server = _make_server()
    resp = _initialize(server)
    assert "result" in resp
    assert resp["result"]["serverInfo"]["name"] == "jsat"


@pytest.mark.ci
def test_no_auth_notifications_initialized_succeeds():
    """notifications/initialized must be silently accepted (no error, no response)."""
    server = _make_server()
    msg = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
    resp = server._handle(msg)
    assert resp is None


# ── JSAT_MCP_ALLOW_INSECURE=1 opt-in ─────────────────────────────────────────

@pytest.mark.ci
def test_allow_insecure_flag_suppresses_warning(monkeypatch):
    """JSAT_MCP_ALLOW_INSECURE=1 sets _allow_insecure=True (silences startup warning)."""
    monkeypatch.setenv("JSAT_MCP_ALLOW_INSECURE", "1")
    monkeypatch.delenv("JSAT_MCP_TOKEN", raising=False)
    monkeypatch.delenv("JSAT_MCP_TOKEN_ROLES", raising=False)
    jsat = MagicMock()
    jsat._cfg.graph.backend = "sqlite"
    jsat._cfg.ai.provider = "anthropic"
    jsat._cfg.ai.model = "claude-3-haiku"
    jsat.index_status = {"nodes": 0, "edges": 0}
    jsat._get_graph.return_value = MagicMock()
    server = MCPServer(jsat)
    assert server._allow_insecure is True
    # Tool calls still proceed (same as no-auth default)
    resp = _tool_call(server, "query")
    if "error" in resp:
        assert resp["error"]["code"] != -32600


# ── Legacy single-token auth (JSAT_MCP_TOKEN) ────────────────────────────────

@pytest.mark.ci
def test_legacy_token_accepts_correct_token(monkeypatch):
    monkeypatch.setenv("JSAT_MCP_TOKEN", "secret123")
    monkeypatch.delenv("JSAT_MCP_TOKEN_ROLES", raising=False)
    monkeypatch.delenv("JSAT_MCP_ALLOW_INSECURE", raising=False)
    jsat = MagicMock()
    jsat._cfg.graph.backend = "sqlite"
    jsat._cfg.ai.provider = "anthropic"
    jsat._cfg.ai.model = "claude-3-haiku"
    jsat.index_status = {"nodes": 0, "edges": 0}
    jsat._get_graph.return_value = MagicMock()
    server = MCPServer(jsat)
    # Correct token — should not get an auth error
    resp = _tool_call(server, "query", token="secret123")
    if "error" in resp:
        assert resp["error"]["code"] != -32600


@pytest.mark.ci
def test_legacy_token_rejects_wrong_token(monkeypatch):
    monkeypatch.setenv("JSAT_MCP_TOKEN", "secret123")
    monkeypatch.delenv("JSAT_MCP_TOKEN_ROLES", raising=False)
    monkeypatch.delenv("JSAT_MCP_ALLOW_INSECURE", raising=False)
    jsat = MagicMock()
    jsat._cfg.graph.backend = "sqlite"
    jsat._cfg.ai.provider = "anthropic"
    jsat._cfg.ai.model = "claude-3-haiku"
    jsat.index_status = {"nodes": 0, "edges": 0}
    server = MCPServer(jsat)
    resp = _tool_call(server, "query", token="wrong")
    assert resp["error"]["code"] == -32600
    assert "Unauthorized" in resp["error"]["message"]


@pytest.mark.ci
def test_legacy_token_rejects_empty_token(monkeypatch):
    monkeypatch.setenv("JSAT_MCP_TOKEN", "secret123")
    monkeypatch.delenv("JSAT_MCP_TOKEN_ROLES", raising=False)
    monkeypatch.delenv("JSAT_MCP_ALLOW_INSECURE", raising=False)
    jsat = MagicMock()
    jsat._cfg.graph.backend = "sqlite"
    jsat._cfg.ai.provider = "anthropic"
    jsat._cfg.ai.model = "claude-3-haiku"
    jsat.index_status = {"nodes": 0, "edges": 0}
    server = MCPServer(jsat)
    resp = _tool_call(server, "query", token="")
    assert resp["error"]["code"] == -32600


# ── RBAC token-roles auth (JSAT_MCP_TOKEN_ROLES) ─────────────────────────────

@pytest.mark.ci
def test_rbac_known_token_accepted(monkeypatch):
    roles = json.dumps({"tok_admin": "admin", "tok_viewer": "viewer"})
    monkeypatch.setenv("JSAT_MCP_TOKEN_ROLES", roles)
    monkeypatch.delenv("JSAT_MCP_TOKEN", raising=False)
    monkeypatch.delenv("JSAT_MCP_ALLOW_INSECURE", raising=False)
    jsat = MagicMock()
    jsat._cfg.graph.backend = "sqlite"
    jsat._cfg.ai.provider = "anthropic"
    jsat._cfg.ai.model = "claude-3-haiku"
    jsat.index_status = {"nodes": 0, "edges": 0}
    jsat._get_graph.return_value = MagicMock()
    server = MCPServer(jsat)
    # admin token calling a tool — should pass RBAC check
    resp = _tool_call(server, "query", token="tok_admin")
    if "error" in resp:
        assert resp["error"]["code"] != -32600


@pytest.mark.ci
def test_rbac_unknown_token_rejected(monkeypatch):
    roles = json.dumps({"tok_admin": "admin"})
    monkeypatch.setenv("JSAT_MCP_TOKEN_ROLES", roles)
    monkeypatch.delenv("JSAT_MCP_TOKEN", raising=False)
    monkeypatch.delenv("JSAT_MCP_ALLOW_INSECURE", raising=False)
    jsat = MagicMock()
    jsat._cfg.graph.backend = "sqlite"
    jsat._cfg.ai.provider = "anthropic"
    jsat._cfg.ai.model = "claude-3-haiku"
    jsat.index_status = {"nodes": 0, "edges": 0}
    server = MCPServer(jsat)
    resp = _tool_call(server, "query", token="unknown_token")
    assert resp["error"]["code"] == -32600
    assert "Unauthorized" in resp["error"]["message"]


@pytest.mark.ci
def test_rbac_viewer_blocked_from_list_secrets(monkeypatch):
    roles = json.dumps({"tok_viewer": "viewer"})
    monkeypatch.setenv("JSAT_MCP_TOKEN_ROLES", roles)
    monkeypatch.delenv("JSAT_MCP_TOKEN", raising=False)
    monkeypatch.delenv("JSAT_MCP_ALLOW_INSECURE", raising=False)
    jsat = MagicMock()
    jsat._cfg.graph.backend = "sqlite"
    jsat._cfg.ai.provider = "anthropic"
    jsat._cfg.ai.model = "claude-3-haiku"
    jsat.index_status = {"nodes": 0, "edges": 0}
    server = MCPServer(jsat)
    resp = _tool_call(server, "list_secrets", token="tok_viewer")
    assert resp["error"]["code"] == -32600
    assert "Forbidden" in resp["error"]["message"]


@pytest.mark.ci
def test_rbac_malformed_json_disables_rbac_gracefully(monkeypatch):
    """Malformed JSAT_MCP_TOKEN_ROLES must not crash the server; RBAC is disabled."""
    monkeypatch.setenv("JSAT_MCP_TOKEN_ROLES", "{not valid json")
    monkeypatch.delenv("JSAT_MCP_TOKEN", raising=False)
    monkeypatch.delenv("JSAT_MCP_ALLOW_INSECURE", raising=False)
    jsat = MagicMock()
    jsat._cfg.graph.backend = "sqlite"
    jsat._cfg.ai.provider = "anthropic"
    jsat._cfg.ai.model = "claude-3-haiku"
    jsat.index_status = {"nodes": 0, "edges": 0}
    # Should not raise during construction
    server = MCPServer(jsat)
    assert server._token_roles == {}
    # Malformed JSON → RBAC disabled, no other token configured → open access with warning
    resp = _tool_call(server, "query")
    # Must NOT be a 401 — tool calls proceed (open access fallback)
    if "error" in resp:
        assert resp["error"]["code"] != -32600


# ── Hard-timeout abandoned-future tracking (thread leak visibility) ─────────

def _slow_tool_call(server: MCPServer, tool_name: str, sleep_s: float, budget_s: float) -> dict:
    """Register a slow test tool and call it with a tiny _budget so the hard
    timeout (5x budget) fires almost immediately while the handler keeps running
    in its abandoned thread for `sleep_s` seconds.
    """
    server._registry[tool_name] = {
        "handler": lambda a: (time.sleep(sleep_s), "slow-done")[1],
        "schema": {"type": "object", "properties": {}},
        "description": "test-only slow tool",
    }
    msg = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": {"_budget": budget_s}, "_auth_token": ""},
    }
    return server._handle(msg) or {}  # type: ignore[return-value]


@pytest.mark.ci
def test_hard_timeout_tracks_abandoned_future():
    """A hard-timed-out call must be recorded in _abandoned_futures instead of
    being silently dropped, since the underlying thread keeps running.
    """
    server = _make_server()
    assert server._abandoned_futures == []

    resp = _slow_tool_call(server, "_test_slow_tool_1", sleep_s=0.3, budget_s=0.01)

    # The hard timeout response is returned to the caller...
    assert "result" in resp
    assert "hard limit" in resp["result"]["content"][0]["text"].lower() or \
        "hard_timeout" in json.dumps(resp)
    # ...but the abandoned future must be tracked, not silently discarded.
    assert len(server._abandoned_futures) == 1
    assert not server._abandoned_futures[0].done()

    # Let the abandoned thread actually finish so it doesn't leak into other tests.
    time.sleep(0.4)
    assert server._abandoned_futures[0].done()


@pytest.mark.ci
def test_new_call_warns_when_abandoned_futures_still_pending():
    """Submitting a new tool call while a prior hard-timed-out future is still
    running must log a visible warning (was previously fully silent).
    """
    server = _make_server()
    server._log = MagicMock()

    _slow_tool_call(server, "_test_slow_tool_2", sleep_s=0.3, budget_s=0.01)
    assert len(server._abandoned_futures) == 1

    # Second call, issued while the first tool's thread is still sleeping.
    # Must go through the full tools/call path (_handle), since the abandoned-
    # futures check happens there, before submitting the new call to the executor.
    resp2 = _tool_call(server, "query")
    assert isinstance(resp2, dict)  # don't care about the tool's own outcome here

    warning_calls = [
        c for c in server._log.warning.call_args_list
        if c.args and c.args[0] == "mcp_abandoned_futures_pending"
    ]
    assert warning_calls, "expected a mcp_abandoned_futures_pending warning to be logged"

    time.sleep(0.4)  # let the abandoned thread finish before test teardown
