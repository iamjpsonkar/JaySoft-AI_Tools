"""Tests for `jsat connect github` — wiring GitHub's MCP server in beside JSAT.

The security-critical property: the PAT's *value* must never reach disk. Only the
environment variable NAME is written, for the MCP client to expand at run time.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from jsat.cli import app

runner = CliRunner()


def _config(tmp_path, tool="claude"):
    rel = {
        "claude": ".claude/settings.json",
        "cursor": ".cursor/mcp.json",
        "codex": ".codex/config.toml",
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
@pytest.mark.parametrize("tool", ["cursor"])
def test_supports_other_tools(tool, tmp_path):
    result = runner.invoke(app, ["connect", "github", tool, "--repo", str(tmp_path)])
    assert result.exit_code == 0
    assert "github" in json.loads(_config(tmp_path, tool).read_text())["mcpServers"]


@pytest.mark.ci
def test_supports_codex_with_global_toml(monkeypatch, tmp_path):
    import jsat._cli_connect as connectmod

    home = tmp_path / "home"
    monkeypatch.setattr(connectmod.Path, "home", classmethod(lambda cls: home))

    result = runner.invoke(app, ["connect", "github", "codex", "--repo", str(tmp_path)])

    assert result.exit_code == 0
    raw = (home / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert "[mcp_servers.github]" in raw
    assert "ghcr.io/github/github-mcp-server" in raw
    assert not (tmp_path / ".codex").exists()


def _opencode_config(repo: Path) -> dict:
    return json.loads((repo / ".opencode" / "opencode.json").read_text())


@pytest.mark.ci
def test_supports_opencode_project_scope_local_docker(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_PERSONAL_ACCESS_TOKEN", "ghp_supersecrettokenvalue123")

    result = runner.invoke(app, ["connect", "github", "opencode", "--repo", str(tmp_path)])
    assert result.exit_code == 0

    cfg = _opencode_config(tmp_path)
    entry = cfg["mcp"]["github"]
    assert entry["type"] == "local"
    assert entry["command"][0] == "docker"
    assert "ghcr.io/github/github-mcp-server" in entry["command"]
    # The token VALUE must never reach disk — only the env var name.
    raw = (tmp_path / ".opencode" / "opencode.json").read_text()
    assert "ghp_supersecrettokenvalue123" not in raw


@pytest.mark.ci
def test_supports_opencode_remote_no_docker(tmp_path):
    result = runner.invoke(app, [
        "connect", "github", "opencode", "--repo", str(tmp_path), "--remote",
    ])
    assert result.exit_code == 0

    entry = _opencode_config(tmp_path)["mcp"]["github"]
    assert entry["type"] == "remote"
    assert entry["url"].startswith("https://api.githubcopilot.com")
    assert "command" not in entry


@pytest.mark.ci
def test_supports_opencode_global_scope_uses_xdg_config_home(tmp_path, monkeypatch):
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))

    result = runner.invoke(app, [
        "connect", "github", "opencode", "--repo", str(tmp_path), "--global",
    ])
    assert result.exit_code == 0

    cfg_path = xdg / "opencode" / "opencode.json"
    assert cfg_path.exists()
    assert "github" in json.loads(cfg_path.read_text())["mcp"]
    assert not (tmp_path / ".opencode").exists()


@pytest.mark.ci
def test_supports_opencode_custom_token_env_wrapped_in_sh(tmp_path):
    result = runner.invoke(app, [
        "connect", "github", "opencode", "--repo", str(tmp_path),
        "--token-env", "MY_GH_TOKEN",
    ])
    assert result.exit_code == 0

    entry = _opencode_config(tmp_path)["mcp"]["github"]
    assert entry["command"][0] == "sh"
    assert "MY_GH_TOKEN" in entry["command"][-1]


@pytest.mark.ci
def test_opencode_preserves_existing_jsat_entry(tmp_path):
    cfg_path = tmp_path / ".opencode" / "opencode.json"
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text(json.dumps({
        "mcp": {"jsat": {"type": "local", "command": ["jsat", "mcp-server"]}},
    }))

    runner.invoke(app, ["connect", "github", "opencode", "--repo", str(tmp_path)])
    cfg = _opencode_config(tmp_path)

    assert cfg["mcp"]["jsat"]["command"] == ["jsat", "mcp-server"]
    assert "github" in cfg["mcp"]


@pytest.mark.ci
@pytest.mark.parametrize("malicious", [
    'X"; touch pwned #',
    "FOO$(touch pwned)",
    "FOO`touch pwned`",
    "FOO; touch pwned",
    "FOO && touch pwned",
])
def test_malicious_token_env_rejected_for_opencode_too(malicious, tmp_path):
    result = runner.invoke(app, [
        "connect", "github", "opencode", "--repo", str(tmp_path),
        "--token-env", malicious,
    ])
    assert result.exit_code != 0
    assert not (tmp_path / ".opencode").exists()


@pytest.mark.ci
def test_malicious_token_env_is_rejected_before_reaching_codex_config(monkeypatch, tmp_path):
    """Bug 1 (Critical, security): shell injection via --token-env in Codex config.

    --token-env is interpolated into a literal `sh -c "..."` command written into
    Codex's config.toml and executed whenever Codex launches the MCP server. A
    value like `X"; touch pwned #` must never reach that string unsanitized.
    """
    import jsat._cli_connect as connectmod

    home = tmp_path / "home"
    monkeypatch.setattr(connectmod.Path, "home", classmethod(lambda cls: home))

    malicious = 'X"; touch pwned #'
    result = runner.invoke(app, [
        "connect", "github", "codex", "--repo", str(tmp_path),
        "--token-env", malicious,
    ])

    # The CLI must reject it outright with a clear error, not write it to disk.
    assert result.exit_code != 0
    assert "Invalid" in result.output or "invalid" in result.output
    config_path = home / ".codex" / "config.toml"
    assert not config_path.exists()


@pytest.mark.ci
@pytest.mark.parametrize("malicious", [
    'X"; touch pwned #',
    "FOO$(touch pwned)",
    "FOO`touch pwned`",
    "FOO; touch pwned",
    "FOO && touch pwned",
    "FOO TOKEN",  # contains a space — not a valid env var name either
])
def test_malicious_token_env_rejected_for_json_config_tools_too(malicious, tmp_path):
    """Same validation must apply to the JSON-config tools (claude/cursor/...),
    not just Codex, since --token-env is a shared option."""
    result = runner.invoke(app, [
        "connect", "github", "--repo", str(tmp_path), "--token-env", malicious,
    ])
    assert result.exit_code != 0
    assert not _config(tmp_path).exists()


@pytest.mark.ci
def test_valid_token_env_names_are_still_accepted(tmp_path):
    for name in ("GITHUB_PAT", "_MY_TOKEN", "TOKEN123"):
        result = runner.invoke(app, [
            "connect", "github", "--repo", str(tmp_path), "--token-env", name,
        ])
        assert result.exit_code == 0
        entry = json.loads(_config(tmp_path).read_text())["mcpServers"]["github"]
        assert entry["env"]["GITHUB_PERSONAL_ACCESS_TOKEN"] == f"${{{name}}}"


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
