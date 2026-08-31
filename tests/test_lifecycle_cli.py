"""CI-safe tests for JSAT-managed AI client lifecycle commands."""
from __future__ import annotations

import os
import signal
import subprocess
import time

import pytest
from typer.testing import CliRunner

from jsat._lifecycle import LifecycleRecord, load_record, save_record
from jsat.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_runtime(monkeypatch, tmp_path):
    monkeypatch.setenv("JSAT_RUNTIME_DIR", str(tmp_path / "runtime"))


@pytest.mark.ci
def test_record_round_trip_omits_commands_and_prompts() -> None:
    record = LifecycleRecord(
        tool="opencode",
        via="ollama",
        repo="/repo",
        model="gemma4:31b-cloud",
        status="running",
    )
    save_record(record)

    loaded = load_record("opencode")
    assert loaded is not None
    assert loaded.tool == "opencode"
    assert loaded.model == "gemma4:31b-cloud"
    assert not hasattr(loaded, "command")
    assert not hasattr(loaded, "arguments")


@pytest.mark.ci
def test_current_process_identity_can_be_validated() -> None:
    from jsat._lifecycle import is_running, process_token

    token = process_token(os.getpid())
    assert token is not None
    assert is_running(LifecycleRecord(
        tool="codex", via="native", repo=".", pid=os.getpid(), process_token=token
    ))
    assert not is_running(LifecycleRecord(
        tool="codex", via="native", repo=".", pid=os.getpid(), process_token="wrong"
    ))


@pytest.mark.ci
def test_stop_refuses_pid_with_wrong_identity(monkeypatch) -> None:
    import jsat._lifecycle as lifecycle

    record = LifecycleRecord(
        tool="claude", via="native", repo=".", pid=999, process_token="old"
    )
    killed: list[tuple[int, signal.Signals]] = []
    monkeypatch.setattr(lifecycle, "is_running", lambda item: False)
    monkeypatch.setattr(os, "kill", lambda pid, sig: killed.append((pid, sig)))

    assert lifecycle.stop_record(record) is False
    assert killed == []


@pytest.mark.ci
def test_run_foreground_tracks_then_clears_pid(monkeypatch, tmp_path) -> None:
    import jsat._lifecycle as lifecycle

    observations: list[str] = []

    class Process:
        pid = 4321

        def wait(self) -> int:
            observations.append(load_record("codex").status)
            return 0

        def poll(self) -> int:
            return 0

    monkeypatch.setattr(subprocess, "Popen", lambda command, cwd: Process())
    monkeypatch.setattr(lifecycle, "process_token", lambda pid: "token-1")
    record = LifecycleRecord(tool="codex", via="native", repo=str(tmp_path))

    assert lifecycle.run_foreground(["codex"], record) == 0
    assert observations == ["running"]
    final = load_record("codex")
    assert final is not None
    assert final.status == "exited"
    assert final.pid is None
    assert final.exit_code == 0


@pytest.mark.ci
@pytest.mark.parametrize(
    ("tool", "session", "expected"),
    [
        ("claude", None, ["--continue"]),
        ("claude", "c-1", ["--resume", "c-1"]),
        ("codex", None, ["resume", "--last"]),
        ("codex", "cx-1", ["resume", "cx-1"]),
        ("opencode", None, ["--continue"]),
        ("opencode", "oc-1", ["--session", "oc-1"]),
    ],
)
def test_native_resume_commands(monkeypatch, tool, session, expected) -> None:
    import jsat._cli_lifecycle as lifecycle_cli

    monkeypatch.setattr(lifecycle_cli, "_native_binary", lambda name: f"/bin/{name}")
    assert lifecycle_cli._build_launch_command(
        tool, via="native", model=None, resume=True, session=session
    ) == [f"/bin/{tool}", *expected]


@pytest.mark.ci
def test_ollama_resume_forwards_to_selected_tool(monkeypatch) -> None:
    import jsat._cli_lifecycle as lifecycle_cli

    monkeypatch.setattr(lifecycle_cli.shutil, "which", lambda name: "/bin/ollama")
    command = lifecycle_cli._build_launch_command(
        "opencode",
        via="ollama",
        model="gemma4:31b-cloud",
        resume=True,
    )
    assert command == [
        "/bin/ollama", "launch", "opencode", "--model", "gemma4:31b-cloud",
        "--", "--continue",
    ]


@pytest.mark.ci
def test_auto_opencode_prefers_ollama_when_only_fallback_binary_exists(monkeypatch) -> None:
    import jsat._cli_lifecycle as lifecycle_cli

    def fake_which(name: str) -> str | None:
        return "/bin/ollama" if name == "ollama" else None

    monkeypatch.setattr(lifecycle_cli.shutil, "which", fake_which)
    monkeypatch.setattr(
        lifecycle_cli, "_native_binary", lambda tool: "/home/user/.opencode/bin/opencode"
    )
    assert lifecycle_cli._resolve_via("opencode", "auto") == "ollama"


@pytest.mark.ci
def test_start_defaults_to_all_in_separate_terminals(monkeypatch, tmp_path) -> None:
    import jsat._cli_lifecycle as lifecycle_cli

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        lifecycle_cli,
        "_fanout",
        lambda action, tools, arguments: captured.update(
            action=action, tools=tools, arguments=arguments
        ),
    )

    result = runner.invoke(app, ["start", "--repo", str(tmp_path)])

    assert result.exit_code == 0
    assert captured["action"] == "start"
    assert captured["tools"] == ["claude", "codex", "opencode"]


@pytest.mark.ci
def test_start_all_model_implies_ollama(monkeypatch) -> None:
    import jsat._cli_lifecycle as lifecycle_cli

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        lifecycle_cli,
        "_fanout",
        lambda action, tools, arguments: captured.update(arguments=arguments),
    )

    result = runner.invoke(app, ["start", "--model", "qwen3:8b"])

    assert result.exit_code == 0
    assert captured["arguments"][:2] == ["--via", "ollama"]


@pytest.mark.ci
def test_restart_defaults_to_all_previous_clients(monkeypatch) -> None:
    import jsat._cli_lifecycle as lifecycle_cli

    save_record(LifecycleRecord(
        tool="opencode", via="ollama", repo="/repo", updated_at=time.time()
    ))
    save_record(LifecycleRecord(
        tool="codex", via="native", repo="/repo", updated_at=time.time() - 1
    ))
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        lifecycle_cli,
        "_fanout",
        lambda action, tools, arguments: captured.update(action=action, tools=tools),
    )

    result = runner.invoke(app, ["restart"])

    assert result.exit_code == 0
    assert captured == {
        "action": "restart",
        "tools": ["claude", "codex", "opencode"],
    }


@pytest.mark.ci
def test_first_restart_safely_starts_all_without_killing_unmanaged(monkeypatch) -> None:
    import jsat._cli_lifecycle as lifecycle_cli

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        lifecycle_cli,
        "_fanout",
        lambda action, tools, arguments: captured.update(action=action, tools=tools),
    )

    result = runner.invoke(app, ["restart"])

    assert result.exit_code == 0
    assert captured == {
        "action": "restart",
        "tools": ["claude", "codex", "opencode"],
    }
    assert "unmanaged processes" in result.output
    assert "left untouched" in result.output


@pytest.mark.ci
def test_resume_all_rejects_one_session_id(monkeypatch) -> None:
    save_record(LifecycleRecord(tool="opencode", via="native", repo="/repo"))
    result = runner.invoke(app, ["resume", "--session", "one-tool-session"])
    assert result.exit_code == 1
    assert "requires one explicit client" in result.output


@pytest.mark.ci
def test_stop_defaults_to_all_running_records(monkeypatch) -> None:
    import jsat._lifecycle as lifecycle

    save_record(LifecycleRecord(tool="claude", via="native", repo="/repo", pid=11))
    save_record(LifecycleRecord(tool="codex", via="native", repo="/repo", pid=12))
    stopped: list[str] = []

    def fake_stop(record, force=False):
        stopped.append(record.tool)
        return True

    monkeypatch.setattr(lifecycle, "is_running", lambda record: True)
    monkeypatch.setattr(lifecycle, "stop_record", fake_stop)

    result = runner.invoke(app, ["stop"])

    assert result.exit_code == 0
    assert stopped == ["codex", "claude"]
    assert "Stopped" in result.output


@pytest.mark.ci
def test_restart_rejects_explicit_model_when_route_is_native() -> None:
    result = runner.invoke(app, ["restart", "opencode", "--via", "native", "--model", "x"])
    assert result.exit_code == 1
    assert "is used only with --via ollama" in result.output


@pytest.mark.ci
def test_resume_rejects_explicit_model_when_route_is_native() -> None:
    result = runner.invoke(app, ["resume", "opencode", "--via", "native", "--model", "x"])
    assert result.exit_code == 1
    assert "is used only with --via ollama" in result.output


@pytest.mark.ci
def test_restart_inherits_stale_model_without_error(monkeypatch) -> None:
    import jsat._cli_lifecycle as lifecycle_cli
    import jsat._lifecycle as lifecycle

    save_record(LifecycleRecord(
        tool="opencode", via="ollama", repo="/repo", model="old-model",
    ))
    monkeypatch.setattr(lifecycle_cli, "_ensure_connected", lambda tool, repo: None)
    monkeypatch.setattr(lifecycle_cli, "_native_binary", lambda tool: "/bin/opencode")
    monkeypatch.setattr(lifecycle, "process_token", lambda pid: "token-1")
    monkeypatch.setattr(subprocess, "Popen", lambda command, cwd: _StubProcess())

    result = runner.invoke(app, ["restart", "opencode", "--via", "native"])

    assert result.exit_code == 0
    assert "old-model" not in result.output


@pytest.mark.ci
def test_launch_status_line_and_record_omit_model_for_native_via(monkeypatch, tmp_path) -> None:
    import jsat._cli_lifecycle as lifecycle_cli
    import jsat._lifecycle as lifecycle
    from jsat._lifecycle import load_record

    monkeypatch.setattr(lifecycle_cli, "_ensure_connected", lambda tool, repo: None)
    monkeypatch.setattr(lifecycle_cli, "_native_binary", lambda tool: "/bin/opencode")
    monkeypatch.setattr(lifecycle, "process_token", lambda pid: "token-1")
    monkeypatch.setattr(subprocess, "Popen", lambda command, cwd: _StubProcess())

    code = lifecycle_cli._launch(
        "opencode", via="native", repo=str(tmp_path), model="stale-model",
    )

    assert code == 0
    record = load_record("opencode")
    assert record is not None
    assert record.model is None


class _StubProcess:
    pid = 5555

    def wait(self) -> int:
        return 0

    def poll(self) -> int:
        return 0


@pytest.mark.ci
def test_ps_lists_all_managed_clients() -> None:
    save_record(LifecycleRecord(tool="opencode", via="ollama", repo="/repo"))
    save_record(LifecycleRecord(tool="claude", via="native", repo="/repo"))
    result = runner.invoke(app, ["ps"])
    assert result.exit_code == 0
    assert "opencode" in result.output
    assert "claude" in result.output
