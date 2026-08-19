"""Codex integration tests.

Codex support is intentionally config-only: one MCP server entry in
``~/.codex/config.toml`` plus one global Codex skill in ``~/.codex/skills/jsat``.
JSAT must not scaffold repo-local Codex instruction or skill files.
"""
from __future__ import annotations

import subprocess
import types

import pytest
from typer.testing import CliRunner

from jsat.cli import app

runner = CliRunner()


@pytest.mark.ci
def test_connect_codex_writes_only_global_config(monkeypatch, tmp_path):
    import jsat._cli_connect as connectmod

    home = tmp_path / "home"
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(connectmod.Path, "home", classmethod(lambda cls: home))

    result = runner.invoke(app, ["connect", "codex", "--repo", str(repo)])

    assert result.exit_code == 0
    config = home / ".codex" / "config.toml"
    raw = config.read_text(encoding="utf-8")
    assert "[mcp_servers.jsat]" in raw
    assert 'args = ["mcp-server"]' in raw
    assert 'JSAT_AI_PROVIDER = "codex_cli"' in raw
    assert str(repo) not in raw

    skill = home / ".codex" / "skills" / "jsat" / "SKILL.md"
    skill_text = skill.read_text(encoding="utf-8")
    assert "name: jsat" in skill_text
    assert "$jsat magic" in skill_text
    assert "@jsat <command>" in skill_text
    assert "Do not delegate this request" in skill_text
    assert "Claude Code" not in skill_text
    assert "by you, Claude" not in skill_text

    assert not (repo / ".codex").exists()
    assert not (repo / "AGENTS.md").exists()
    assert not (repo / ".agents").exists()


@pytest.mark.ci
def test_connect_codex_no_instructions_skips_global_skill(monkeypatch, tmp_path):
    import jsat._cli_connect as connectmod

    home = tmp_path / "home"
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(connectmod.Path, "home", classmethod(lambda cls: home))

    result = runner.invoke(app, ["connect", "codex", "--repo", str(repo), "--no-instructions"])

    assert result.exit_code == 0
    assert (home / ".codex" / "config.toml").exists()
    assert not (home / ".codex" / "skills" / "jsat" / "SKILL.md").exists()
    assert not (repo / ".codex").exists()
    assert not (repo / "AGENTS.md").exists()
    assert not (repo / ".agents").exists()


@pytest.mark.ci
def test_jsat_codex_autoconnect_is_global_and_launches_in_repo(monkeypatch, tmp_path):
    import shutil

    import jsat._cli_launchers as launchmod

    home = tmp_path / "home"
    repo = tmp_path / "repo"
    repo.mkdir()
    global_config = home / ".codex" / "config.toml"
    monkeypatch.setitem(
        launchmod._TOOL_CONFIG_PATHS, "codex", (global_config, "mcpServers")
    )
    monkeypatch.setattr(shutil, "which", lambda name: f"/fake/bin/{name}")

    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = kwargs.get("cwd")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = runner.invoke(app, ["codex", "--repo", str(repo)])

    assert result.exit_code == 0
    assert captured["cmd"] == ["/fake/bin/codex"]
    assert captured["cwd"] == str(repo.resolve())
    assert "[mcp_servers.jsat]" in global_config.read_text(encoding="utf-8")
    assert (home / ".codex" / "skills" / "jsat" / "SKILL.md").exists()
    assert not (repo / ".codex").exists()
    assert not (repo / "AGENTS.md").exists()
    assert not (repo / ".agents").exists()


@pytest.mark.ci
def test_jsat_codex_forwards_resume_args(monkeypatch, tmp_path):
    import shutil

    import jsat._cli_launchers as launchmod

    home = tmp_path / "home"
    repo = tmp_path / "repo"
    repo.mkdir()
    global_config = home / ".codex" / "config.toml"
    monkeypatch.setitem(
        launchmod._TOOL_CONFIG_PATHS, "codex", (global_config, "mcpServers")
    )
    monkeypatch.setattr(shutil, "which", lambda name: f"/fake/bin/{name}")

    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = kwargs.get("cwd")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = runner.invoke(
        app,
        [
            "codex",
            "--repo",
            str(repo),
            "resume",
            "01a00e7d-73e3-7212-9151-98150623c97c",
        ],
    )

    assert result.exit_code == 0
    assert captured["cmd"] == [
        "/fake/bin/codex",
        "resume",
        "01a00e7d-73e3-7212-9151-98150623c97c",
    ]
    assert captured["cwd"] == str(repo.resolve())
    assert "[mcp_servers.jsat]" in global_config.read_text(encoding="utf-8")
    assert (home / ".codex" / "skills" / "jsat" / "SKILL.md").exists()
    assert not (repo / ".codex").exists()
    assert not (repo / "AGENTS.md").exists()
    assert not (repo / ".agents").exists()


@pytest.mark.ci
def test_jsat_codex_rewrites_legacy_repo_pinned_entry(monkeypatch, tmp_path):
    import shutil

    import jsat._cli_launchers as launchmod

    home = tmp_path / "home"
    repo = tmp_path / "repo"
    repo.mkdir()
    global_config = home / ".codex" / "config.toml"
    global_config.parent.mkdir(parents=True)
    global_config.write_text(
        '[mcp_servers.jsat]\ncommand = "jsat"\n'
        'args = ["mcp-server", "--repo", "/old/repo"]\n',
        encoding="utf-8",
    )
    monkeypatch.setitem(
        launchmod._TOOL_CONFIG_PATHS, "codex", (global_config, "mcpServers")
    )
    monkeypatch.setattr(shutil, "which", lambda name: f"/fake/bin/{name}")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 0),
    )

    result = runner.invoke(app, ["codex", "--repo", str(repo)])

    assert result.exit_code == 0
    raw = global_config.read_text(encoding="utf-8")
    assert 'args = ["mcp-server"]' in raw
    assert "--repo" not in raw
    assert "/old/repo" not in raw
    assert (home / ".codex" / "skills" / "jsat" / "SKILL.md").exists()


@pytest.mark.ci
def test_disconnect_codex_removes_global_skill(monkeypatch, tmp_path):
    import jsat._cli_setup as setupmod

    home = tmp_path / "home"
    config = home / ".codex" / "config.toml"
    skill = home / ".codex" / "skills" / "jsat" / "SKILL.md"
    config.parent.mkdir(parents=True)
    skill.parent.mkdir(parents=True)
    config.write_text('[mcp_servers.jsat]\ncommand = "jsat"\nargs = ["mcp-server"]\n')
    skill.write_text("---\nname: jsat\n---\n", encoding="utf-8")
    monkeypatch.setattr(setupmod.Path, "home", classmethod(lambda cls: home))

    result = runner.invoke(app, ["disconnect", "codex"])

    assert result.exit_code == 0
    assert "[mcp_servers.jsat]" not in config.read_text(encoding="utf-8")
    assert not skill.exists()


@pytest.mark.ci
def test_codex_cli_provider_exec_is_read_only_and_ephemeral(monkeypatch, tmp_path):
    import shutil

    from jsat._ai.codex_cli import CodexCliProvider

    monkeypatch.setattr(shutil, "which", lambda name: "/fake/bin/codex")
    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = kwargs.get("cwd")
        captured["input"] = kwargs.get("input")
        return subprocess.CompletedProcess(cmd, 0, stdout="answer\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    cfg = types.SimpleNamespace(
        ai=types.SimpleNamespace(model="gpt-5.6-sol", timeout_seconds=30)
    )
    provider = CodexCliProvider(cfg)
    provider.configure(repo_dir=str(tmp_path), stateful=False)

    assert provider.complete("explain this") == "answer"

    cmd = captured["cmd"]
    assert isinstance(cmd, list)
    assert cmd[:7] == [
        "/fake/bin/codex",
        "exec",
        "--config",
        'approval_policy="never"',
        "--sandbox",
        "read-only",
        "--ephemeral",
    ]
    assert ["--cd", str(tmp_path)] == cmd[7:9]
    assert cmd[-1] == "-"
    assert "--ask-for-approval" not in cmd
    assert "explain this" not in cmd
    assert captured["input"] == "explain this"
    assert captured["cwd"] == str(tmp_path)
