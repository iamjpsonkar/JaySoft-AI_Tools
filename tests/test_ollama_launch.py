"""Ollama local/cloud model selection and coding-tool launcher tests."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from jsat._ollama import (
    build_ollama_launch_args,
    ollama_model_kind,
    ollama_models_match,
)
from jsat.cli import app

runner = CliRunner()


@pytest.mark.ci
@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("qwen3.5", "local"),
        ("gpt-oss:20b", "local"),
        ("gemma4:cloud", "cloud"),
        ("gemma4:31b-cloud", "cloud"),
        ("GLM-5:CLOUD", "cloud"),
    ],
)
def test_ollama_model_kind_uses_cloud_suffix(model: str, expected: str) -> None:
    assert ollama_model_kind(model) == expected


@pytest.mark.ci
def test_ollama_model_match_does_not_confuse_distinct_tags() -> None:
    assert ollama_models_match("qwen3.5:latest", "qwen3.5")
    assert not ollama_models_match("gpt-oss:20b", "gpt-oss:120b-cloud")
    assert not ollama_models_match("qwen3.5:cloud", "qwen3.5")


@pytest.mark.ci
def test_build_ollama_launch_args_preserves_ollama_cli_order() -> None:
    assert build_ollama_launch_args(
        "claude",
        model="gemma4:cloud",
        yes=True,
        passthrough=["-p", "explain this repo"],
    ) == [
        "launch",
        "claude",
        "--model",
        "gemma4:cloud",
        "--yes",
        "--",
        "-p",
        "explain this repo",
    ]


@pytest.mark.ci
def test_build_ollama_launch_args_requires_model_for_yes() -> None:
    with pytest.raises(ValueError, match="--yes requires --model"):
        build_ollama_launch_args("opencode", yes=True)


@pytest.mark.ci
def test_build_ollama_launch_args_restore_is_bare() -> None:
    # docs.ollama.com/integrations/codex shows `ollama launch codex --restore` as a
    # standalone flag, never combined with --config/--model/--yes.
    assert build_ollama_launch_args("codex", restore=True) == ["launch", "codex", "--restore"]


@pytest.mark.ci
def test_build_ollama_launch_args_restore_rejects_combination() -> None:
    with pytest.raises(ValueError, match="--restore cannot be combined"):
        build_ollama_launch_args("codex", restore=True, model="qwen3.5")


@pytest.mark.ci
def test_jsat_ollama_tool_propagates_nonzero_exit_code(monkeypatch, tmp_path) -> None:
    import shutil

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "home" / ".config"))
    monkeypatch.setattr(shutil, "which", lambda name: "/fake/bin/ollama")
    monkeypatch.setattr(
        subprocess, "run", lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 3)
    )

    result = runner.invoke(app, ["ollama", "--repo", str(tmp_path), "--tool", "claude"])

    assert result.exit_code == 3


@pytest.mark.ci
def test_jsat_ollama_tool_restore_forwards_flag(monkeypatch, tmp_path) -> None:
    import shutil

    monkeypatch.setattr(shutil, "which", lambda name: "/fake/bin/ollama")
    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = runner.invoke(
        app, ["ollama", "--repo", str(tmp_path), "--tool", "codex", "--restore"]
    )

    assert result.exit_code == 0
    assert captured["cmd"] == ["/fake/bin/ollama", "launch", "codex", "--restore"]


@pytest.mark.ci
def test_jsat_ollama_tool_launches_in_repo(monkeypatch, tmp_path) -> None:
    import shutil

    config = tmp_path / "home" / ".config" / "opencode" / "opencode.json"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "home" / ".config"))
    looked_up: list[str] = []

    def fake_which(name: str) -> str | None:
        looked_up.append(name)
        return "/fake/bin/ollama" if name == "ollama" else None

    monkeypatch.setattr(shutil, "which", fake_which)
    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = kwargs.get("cwd")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = runner.invoke(
        app,
        [
            "ollama",
            "--repo",
            str(tmp_path),
            "--tool",
            "opencode",
            "--model",
            "qwen3.5",
        ],
    )

    assert result.exit_code == 0
    assert captured["cmd"] == [
        "/fake/bin/ollama",
        "launch",
        "opencode",
        "--model",
        "qwen3.5",
    ]
    assert captured["cwd"] == str(tmp_path.resolve())
    assert "Local model" in result.output
    assert looked_up == ["ollama", "jsat"]
    assert "opencode" not in looked_up
    assert '"mcp"' in config.read_text(encoding="utf-8")
    assert '"jsat"' in config.read_text(encoding="utf-8")
    commands = config.parent / "commands"
    assert (commands / "jsat.md").exists()
    assert (commands / "jsat-help.md").exists()


@pytest.mark.ci
def test_jsat_ollama_repairs_existing_opencode_provider_marker(monkeypatch, tmp_path) -> None:
    import json
    import shutil

    config = tmp_path / "xdg" / "opencode" / "opencode.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({
        "mcp": {"jsat": {
            "type": "local",
            "command": ["jsat", "mcp-server"],
            "enabled": True,
            "environment": {"JSAT_MCP_ALLOW_INSECURE": "1"},
        }}
    }), encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(shutil, "which", lambda name: f"/fake/bin/{name}")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 0),
    )

    result = runner.invoke(app, ["ollama", "--tool", "opencode", "--model", "qwen3:8b"])

    assert result.exit_code == 0
    entry = json.loads(config.read_text(encoding="utf-8"))["mcp"]["jsat"]
    assert entry["environment"]["JSAT_AI_PROVIDER"] == "opencode_cli"
    assert (config.parent / "commands" / "jsat.md").exists()


@pytest.mark.ci
def test_jsat_ollama_tool_without_model_keeps_interactive_selector(monkeypatch, tmp_path) -> None:
    import shutil

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "home" / ".config"))
    monkeypatch.setattr(shutil, "which", lambda name: "/fake/bin/ollama")
    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = runner.invoke(app, ["ollama", "--repo", str(tmp_path), "--tool", "claude"])

    assert result.exit_code == 0
    assert captured["cmd"] == ["/fake/bin/ollama", "launch", "claude"]
    assert "choose local or cloud" in result.output


@pytest.mark.ci
def test_ollama_positional_tool_name_routes_to_tool_launch(monkeypatch, tmp_path) -> None:
    import shutil

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "home" / ".config"))
    monkeypatch.setattr(shutil, "which", lambda name: "/fake/bin/ollama")
    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = runner.invoke(
        app, ["ollama", "--repo", str(tmp_path), "opencode", "--model", "qwen3.5"]
    )

    assert result.exit_code == 0
    assert captured["cmd"] == ["/fake/bin/ollama", "launch", "opencode", "--model", "qwen3.5"]


@pytest.mark.ci
def test_ollama_positional_non_tool_routes_to_model(monkeypatch) -> None:
    import jsat._cli_launchers as launchmod
    import jsat.tools.shell as shellmod

    calls: dict[str, object] = {}

    class FakeJSAT:
        def switch_ai(self, provider: str, model: str) -> None:
            calls["switch"] = (provider, model)

    monkeypatch.setattr(launchmod, "_jsat", lambda **kwargs: FakeJSAT())
    monkeypatch.setattr(shellmod, "launch", lambda js: calls.setdefault("launched", js))

    result = runner.invoke(app, ["ollama", "qwen3.5"])

    assert result.exit_code == 0
    assert calls["switch"] == ("ollama", "qwen3.5")


@pytest.mark.ci
@pytest.mark.parametrize(
    "args",
    [
        ["ollama", "opencode", "--tool", "claude"],
        ["ollama", "qwen3.5", "--model", "other-model"],
    ],
)
def test_ollama_positional_and_flag_conflict_errors(args) -> None:
    result = runner.invoke(app, args)

    assert result.exit_code == 1
    assert "choose either" in result.output


@pytest.mark.ci
def test_plain_jsat_ollama_preserves_internal_shell(monkeypatch) -> None:
    import jsat._cli_launchers as launchmod
    import jsat.tools.shell as shellmod

    calls: dict[str, object] = {}

    class FakeJSAT:
        def switch_ai(self, provider: str, model: str) -> None:
            calls["switch"] = (provider, model)

    monkeypatch.setattr(launchmod, "_jsat", lambda **kwargs: FakeJSAT())
    monkeypatch.setattr(shellmod, "launch", lambda js: calls.setdefault("launched", js))
    import jsat._ollama as ollama_helpers

    monkeypatch.setattr(ollama_helpers, "discover_ollama_models", lambda: ["detected-model"])

    result = runner.invoke(app, ["ollama"])

    assert result.exit_code == 0
    assert calls["switch"] == ("ollama", "detected-model")
    assert isinstance(calls["launched"], FakeJSAT)


@pytest.mark.ci
def test_direct_ollama_reuses_persisted_ai_use_model(monkeypatch) -> None:
    import types

    import jsat._cli_launchers as launchmod
    import jsat._ollama as ollama_helpers
    import jsat.tools.shell as shellmod

    calls: dict[str, object] = {}

    class FakeJSAT:
        _cfg = types.SimpleNamespace(ai=types.SimpleNamespace(provider="ollama", model="qwen3.5"))

        def switch_ai(self, provider: str, model: str) -> None:
            calls["switch"] = (provider, model)

    monkeypatch.setattr(launchmod, "_jsat", lambda **kwargs: FakeJSAT())
    monkeypatch.setattr(shellmod, "launch", lambda js: calls.setdefault("launched", js))

    def _unexpected_discovery() -> list[str]:
        raise AssertionError("discovery should be skipped when a model is persisted")

    monkeypatch.setattr(ollama_helpers, "discover_ollama_models", _unexpected_discovery)

    result = runner.invoke(app, ["ollama"])

    assert result.exit_code == 0
    assert calls["switch"] == ("ollama", "qwen3.5")
    assert "Using the configured Ollama model" in result.output


@pytest.mark.ci
def test_direct_ollama_auto_selects_only_registered_model() -> None:
    from jsat._ollama import select_ollama_model

    assert select_ollama_model(None, ["only-model:latest"]) == "only-model:latest"


@pytest.mark.ci
def test_direct_ollama_asks_when_model_is_ambiguous() -> None:
    from jsat._ollama import select_ollama_model

    with pytest.raises(ValueError) as exc:
        select_ollama_model(None, ["first", "second"])
    message = str(exc.value)
    assert "ollama list" in message
    assert "jsat ai models ollama" in message
    assert "jsat ai use ollama --model <model>" in message


@pytest.mark.ci
def test_ollama_preflight_rejects_empty_registered_model_list(monkeypatch) -> None:
    import httpx

    from jsat._cli_ai import _preflight_ollama

    class Response:
        def raise_for_status(self): return None
        def json(self): return {"models": []}

    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: Response())

    assert _preflight_ollama("missing-model") is False


@pytest.mark.ci
def test_ai_use_does_not_save_unregistered_ollama_model(monkeypatch, tmp_path) -> None:
    import httpx

    class Response:
        def raise_for_status(self): return None
        def json(self): return {"models": []}

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: Response())

    result = runner.invoke(app, ["ai", "use", "ollama", "--model", "missing-model"])

    assert result.exit_code == 1
    assert "not registered" in result.output
    assert not (tmp_path / ".jsat" / "config.yaml").exists()


@pytest.mark.ci
def test_connect_opencode_needs_no_opencode_binary(monkeypatch, tmp_path) -> None:
    import json
    import shutil

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(shutil, "which", lambda name: None)

    result = runner.invoke(app, ["connect", "opencode"])

    assert result.exit_code == 0
    config = tmp_path / "xdg" / "opencode" / "opencode.json"
    data = json.loads(config.read_text(encoding="utf-8"))
    entry = data["mcp"]["jsat"]
    assert entry["type"] == "local"
    assert entry["command"][-1] == "mcp-server"
    assert "--repo" not in entry["command"]
    assert entry["enabled"] is True
    assert entry["environment"]["JSAT_AI_PROVIDER"] == "opencode_cli"
    commands = config.parent / "commands"
    assert "/jsat <command>" in (commands / "jsat.md").read_text(encoding="utf-8")
    assert (commands / "jsat-help.md").exists()


@pytest.mark.ci
def test_connect_opencode_can_skip_slash_commands(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    result = runner.invoke(app, ["connect", "opencode", "--no-commands"])

    assert result.exit_code == 0
    base = tmp_path / "xdg" / "opencode"
    assert (base / "opencode.json").exists()
    assert not (base / "commands").exists()


@pytest.mark.ci
def test_connect_opencode_preserves_settings_and_is_idempotent(monkeypatch, tmp_path) -> None:
    import json

    config = tmp_path / "xdg" / "opencode" / "opencode.json"
    config.parent.mkdir(parents=True)
    config.write_text(
        json.dumps({"theme": "system", "mcp": {"other": {"type": "remote"}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    first = runner.invoke(app, ["connect", "opencode"])
    second = runner.invoke(app, ["connect", "opencode"])

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert "Updated" in second.output
    data = json.loads(config.read_text(encoding="utf-8"))
    assert data["theme"] == "system"
    assert "other" in data["mcp"]
    assert "jsat" in data["mcp"]


@pytest.mark.ci
def test_connect_opencode_does_not_overwrite_invalid_config(monkeypatch, tmp_path) -> None:
    config = tmp_path / "xdg" / "opencode" / "opencode.json"
    config.parent.mkdir(parents=True)
    original = "{ // user JSONC that stdlib json cannot safely merge\n}"
    config.write_text(original, encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    result = runner.invoke(app, ["connect", "opencode"])

    assert result.exit_code == 1
    assert "left it unchanged" in result.output
    assert config.read_text(encoding="utf-8") == original


@pytest.mark.ci
def test_disconnect_opencode_removes_only_jsat(monkeypatch, tmp_path) -> None:
    import json

    config = tmp_path / "xdg" / "opencode" / "opencode.json"
    config.parent.mkdir(parents=True)
    config.write_text(
        json.dumps({"mcp": {"jsat": {"type": "local"}, "other": {"type": "remote"}}}),
        encoding="utf-8",
    )
    commands = config.parent / "commands"
    commands.mkdir()
    (commands / "jsat.md").write_text("JSAT dispatcher", encoding="utf-8")
    (commands / "jsat-help.md").write_text("JSAT help", encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    result = runner.invoke(app, ["disconnect", "opencode"])

    assert result.exit_code == 0
    data = json.loads(config.read_text(encoding="utf-8"))
    assert "jsat" not in data["mcp"]
    assert "other" in data["mcp"]
    assert not (commands / "jsat.md").exists()
    assert not (commands / "jsat-help.md").exists()


@pytest.mark.ci
@pytest.mark.parametrize(
    "args",
    [
        ["connect", "ollama", "opencode"],
        ["connect", "ollama", "tool=opencode"],
        ["connect", "ollama", "--tool", "opencode"],
    ],
)
def test_connect_ollama_accepts_each_tool_selector(monkeypatch, args) -> None:
    import jsat._cli_connect as connect_module

    connected: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        connect_module,
        "_connect_ollama_target",
        lambda target, show: connected.append((target, show)),
    )

    result = runner.invoke(app, args)

    assert result.exit_code == 0
    assert connected == [("opencode", False)]


@pytest.mark.ci
def test_connect_ollama_defaults_to_all_supported_clients(monkeypatch) -> None:
    import jsat._cli_connect as connect_module

    connected: list[str] = []
    monkeypatch.setattr(
        connect_module,
        "_connect_ollama_target",
        lambda target, show: connected.append(target),
    )

    result = runner.invoke(app, ["connect", "ollama"])

    assert result.exit_code == 0
    assert connected == ["claude", "codex", "opencode"]


@pytest.mark.ci
def test_connect_ollama_all_continues_after_one_client_fails(monkeypatch) -> None:
    import jsat._cli_connect as connect_module

    connected: list[str] = []

    def connect(target: str, show: bool) -> None:
        connected.append(target)
        if target == "codex":
            raise ValueError("broken config")

    monkeypatch.setattr(connect_module, "_connect_ollama_target", connect)

    result = runner.invoke(app, ["connect", "ollama"])

    assert result.exit_code == 1
    assert connected == ["claude", "codex", "opencode"]
    assert "failed: codex" in result.output


@pytest.mark.ci
def test_connect_ollama_persists_model_for_tool(monkeypatch, tmp_path) -> None:
    import yaml

    import jsat._cli_connect as connect_module

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    monkeypatch.setattr(connect_module, "_connect_ollama_target", lambda target, show: None)

    result = runner.invoke(
        app, ["connect", "ollama", "opencode", "--model", "gemma4:31b-cloud"]
    )

    assert result.exit_code == 0
    cfg_path = tmp_path / "home" / ".jsat" / "config.yaml"
    data = yaml.safe_load(cfg_path.read_text())
    assert data["ai"]["ollama_tool_models"]["opencode"] == "gemma4:31b-cloud"
    assert "will default to model" in result.output


@pytest.mark.ci
def test_connect_ollama_rejects_model_with_all_target(monkeypatch) -> None:
    import jsat._cli_connect as connect_module

    monkeypatch.setattr(connect_module, "_connect_ollama_target", lambda target, show: None)

    result = runner.invoke(app, ["connect", "ollama", "--model", "gemma4:31b-cloud"])

    assert result.exit_code == 1
    assert "requires a single TOOL target" in result.output


@pytest.mark.ci
def test_launch_with_ollama_reuses_persisted_tool_model(monkeypatch, tmp_path) -> None:
    import shutil

    import yaml

    home = tmp_path / "home"
    cfg_path = home / ".jsat" / "config.yaml"
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text(yaml.dump({"ai": {"ollama_tool_models": {"opencode": "gemma4:31b-cloud"}}}))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "home" / ".config"))
    monkeypatch.setattr(shutil, "which", lambda name: "/fake/bin/ollama")
    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = runner.invoke(app, ["ollama", "--repo", str(tmp_path), "--tool", "opencode"])

    assert result.exit_code == 0
    assert captured["cmd"] == [
        "/fake/bin/ollama", "launch", "opencode", "--model", "gemma4:31b-cloud",
    ]
    assert "Using the model connected for this tool" in result.output


@pytest.mark.ci
def test_connect_ollama_rejects_unknown_client() -> None:
    result = runner.invoke(app, ["connect", "ollama", "openclaw"])

    assert result.exit_code == 1
    assert "unsupported Ollama connection target" in result.output


@pytest.mark.ci
def test_disconnect_ollama_removes_only_supported_client_configs(monkeypatch, tmp_path) -> None:
    import json

    import jsat._cli_setup as setup_module

    home = tmp_path / "home"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(setup_module.Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))

    claude = home / ".claude" / "settings.json"
    claude.parent.mkdir(parents=True)
    claude.write_text(json.dumps({"mcpServers": {"jsat": {}, "other": {}}}))

    codex = home / ".codex" / "config.toml"
    codex.parent.mkdir(parents=True)
    codex.write_text('[mcp_servers.jsat]\ncommand = "jsat"\n', encoding="utf-8")

    opencode = home / ".config" / "opencode" / "opencode.json"
    opencode.parent.mkdir(parents=True)
    opencode.write_text(json.dumps({"mcp": {"jsat": {}, "other": {}}}))
    opencode_commands = opencode.parent / "commands"
    opencode_commands.mkdir()
    (opencode_commands / "jsat.md").write_text("JSAT dispatcher", encoding="utf-8")

    cursor = home / ".cursor" / "mcp.json"
    cursor.parent.mkdir(parents=True)
    cursor.write_text(json.dumps({"mcpServers": {"jsat": {}}}))

    result = runner.invoke(app, ["disconnect", "ollama"])

    assert result.exit_code == 0
    assert "jsat" not in json.loads(claude.read_text())["mcpServers"]
    assert "[mcp_servers.jsat]" not in codex.read_text()
    assert "jsat" not in json.loads(opencode.read_text())["mcp"]
    assert not (opencode_commands / "jsat.md").exists()
    assert "jsat" in json.loads(cursor.read_text())["mcpServers"]
