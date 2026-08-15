"""Tests for `jsat connect github` — wiring GitHub's MCP server in beside JSAT.

The security-critical property: the PAT's *value* must never reach disk. Only the
environment variable NAME is written, for the MCP client to expand at run time.
"""
from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from jsat.cli import app

runner = CliRunner()


def _config(tmp_path, tool="claude"):
    rel = {
        "claude": ".claude/settings.json",
        "cursor": ".cursor/mcp.json",
        "codex": ".codex/config.json",
    }[tool]
    return tmp_path / rel


@pytest.mark.ci
def test_writes_docker_entry_by_default(tmp_path):
    result = runner.invoke(app, ["connect", "github", "--repo", str(tmp_path)])
    assert result.exit_code == 0

    cfg = json.loads(_config(tmp_path).read_text())
    entry = cfg["mcpServers"]["github"]
    assert entry["command"] == "docker"
    assert "ghcr.io/github/github-mcp-server" in entry["args"]


@pytest.mark.ci
def test_token_value_never_written_to_disk(tmp_path, monkeypatch):
    """The whole point: config stores the env var NAME, never the secret."""
    monkeypatch.setenv("GITHUB_PERSONAL_ACCESS_TOKEN", "ghp_supersecrettokenvalue123")

    runner.invoke(app, ["connect", "github", "--repo", str(tmp_path)])
    raw = _config(tmp_path).read_text()

    assert "ghp_supersecrettokenvalue123" not in raw
    assert "${GITHUB_PERSONAL_ACCESS_TOKEN}" in raw


@pytest.mark.ci
def test_custom_token_env_name_is_honoured(tmp_path):
    runner.invoke(app, ["connect", "github", "--repo", str(tmp_path),
                        "--token-env", "MY_GH_TOKEN"])
    entry = json.loads(_config(tmp_path).read_text())["mcpServers"]["github"]
    assert entry["env"]["GITHUB_PERSONAL_ACCESS_TOKEN"] == "${MY_GH_TOKEN}"


@pytest.mark.ci
def test_remote_uses_http_transport_and_no_docker(tmp_path):
    runner.invoke(app, ["connect", "github", "--repo", str(tmp_path), "--remote"])
    entry = json.loads(_config(tmp_path).read_text())["mcpServers"]["github"]
    assert entry["type"] == "http"
    assert entry["url"].startswith("https://api.githubcopilot.com")
    assert "command" not in entry


@pytest.mark.ci
def test_preserves_existing_jsat_entry(tmp_path):
    """Adding GitHub must not clobber the JSAT server already in the config."""
    cfg_path = _config(tmp_path)
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text(json.dumps({
        "mcpServers": {"jsat": {"command": "jsat", "args": ["mcp-server"]}},
        "otherSetting": True,
    }))

    runner.invoke(app, ["connect", "github", "--repo", str(tmp_path)])
    cfg = json.loads(cfg_path.read_text())

    assert cfg["mcpServers"]["jsat"]["command"] == "jsat"
    assert "github" in cfg["mcpServers"]
    assert cfg["otherSetting"] is True


@pytest.mark.ci
def test_warns_when_jsat_not_yet_connected(tmp_path):
    result = runner.invoke(app, ["connect", "github", "--repo", str(tmp_path)])
    assert "jsat connect claude" in result.output


@pytest.mark.ci
@pytest.mark.parametrize("tool", ["cursor", "codex"])
def test_supports_other_tools(tool, tmp_path):
    result = runner.invoke(app, ["connect", "github", tool, "--repo", str(tmp_path)])
    assert result.exit_code == 0
    assert "github" in json.loads(_config(tmp_path, tool).read_text())["mcpServers"]


@pytest.mark.ci
def test_unknown_tool_suggests_closest(tmp_path):
    result = runner.invoke(app, ["connect", "github", "cursr", "--repo", str(tmp_path)])
    assert result.exit_code == 1
    assert "cursor" in result.output


@pytest.mark.ci
def test_rerun_is_idempotent(tmp_path):
    runner.invoke(app, ["connect", "github", "--repo", str(tmp_path)])
    first = _config(tmp_path).read_text()
    result = runner.invoke(app, ["connect", "github", "--repo", str(tmp_path)])

    assert _config(tmp_path).read_text() == first
    assert "Updated" in result.output


@pytest.mark.ci
def test_guidance_block_documents_the_github_workflow():
    """CLAUDE.md and friends must tell the AI how to pair JSAT with GitHub MCP."""
    from jsat._cli_connect import _jsat_instructions_block

    block = _jsat_instructions_block()
    assert "GitHub MCP" in block
    assert "Search before filing" in block
    # The privacy rule must be explicit, not implied.
    assert "Never paste raw errors" in block
