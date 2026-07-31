"""Tests for jsat.mcp.server — RBAC, auth, and fail-closed behaviour."""
from __future__ import annotations

import json
import os
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
def test_no_auth_no_insecure_rejects_tool_calls():
    """Default state (no env vars set) must reject all tool calls."""
    server = _make_server()
    resp = _tool_call(server, "query")
    assert resp["error"]["code"] == -32600
    assert "Unauthorized" in resp["error"]["message"]
    assert "JSAT_MCP_ALLOW_INSECURE" in resp["error"]["message"]


@pytest.mark.ci
def test_no_auth_no_insecure_rejects_tools_list():
    """tools/list should also be rejected when no auth is configured."""
    server = _make_server()
    msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    resp = server._handle(msg)
    assert resp is not None and resp["error"]["code"] == -32600


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
def test_allow_insecure_permits_tool_calls(monkeypatch):
    """JSAT_MCP_ALLOW_INSECURE=1 must allow unauthenticated tool calls to proceed."""
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
    # _handle should not return an auth error; the tool may fail (unknown), but not 401
    resp = _tool_call(server, "query")
    # Either succeeds or fails with a non-auth error (e.g. tool runtime error)
    if "error" in resp:
        assert resp["error"]["code"] != -32600 or "Unauthorized" not in resp["error"]["message"]


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
    # With no valid auth configured, tool calls must be rejected (fail-closed)
    resp = _tool_call(server, "query")
    assert resp["error"]["code"] == -32600
