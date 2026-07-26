"""Tests for the Bob Shell integration.

Covers:
  - jsat._ai.bob_cli.BobCliProvider — arg building, complete(), streaming,
    session state, timeout/error handling.
  - jsat._ai.get_ai_provider factory dispatch to BobCliProvider.
  - jsat._models.AIConfig accepting the "bob_cli" provider.
  - jsat._config Bob provider detection/reachability + priority ordering.
  - jsat.tools.shell.launch_ai_with_jsat_tools launching Bob as a clean
    INTERACTIVE session (no injected prompt, so it never runs one-shot).

All external processes (the `bob` binary) are mocked — no real subprocess runs.
"""
import subprocess
import types

import pytest

from jsat._ai import bob_cli as bob_mod
from jsat._ai.bob_cli import BobCliProvider
from jsat._exceptions import AITimeoutError

# ── helpers ────────────────────────────────────────────────────────────────

class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _cfg(provider="bob_cli", model="premium", **ai_extra):
    """Minimal cfg-like object with a .ai attribute."""
    ai = types.SimpleNamespace(provider=provider, model=model,
                               chat_mode=ai_extra.get("chat_mode"),
                               timeout_seconds=ai_extra.get("timeout_seconds", 180))
    return types.SimpleNamespace(ai=ai)


@pytest.fixture
def bob_present(monkeypatch):
    """Make shutil.which('bob') resolve to a fake path inside bob_cli."""
    monkeypatch.setattr(bob_mod.shutil, "which",
                        lambda name: "/fake/bin/bob" if name == "bob" else None)


# ── identity / availability ──────────────────────────────────────────────────

@pytest.mark.ci
def test_provider_and_model_name(bob_present):
    p = BobCliProvider(_cfg(model="premium"))
    assert p.provider_name == "bob_cli"
    assert p.model_name == "premium"


@pytest.mark.ci
def test_is_available_reflects_binary(monkeypatch):
    monkeypatch.setattr(bob_mod.shutil, "which", lambda name: None)
    assert BobCliProvider(_cfg()).is_available() is False
    monkeypatch.setattr(bob_mod.shutil, "which",
                        lambda name: "/fake/bin/bob" if name == "bob" else None)
    assert BobCliProvider(_cfg()).is_available() is True


# ── _build_args ──────────────────────────────────────────────────────────────

@pytest.mark.ci
def test_build_args_stateless_default(bob_present):
    p = BobCliProvider(_cfg())
    args = p._build_args("hello", stream=False)
    assert args[0] == p._binary
    assert "--chat-mode" in args and "advanced" in args   # default mode
    assert args[args.index("--output-format") + 1] == "text"
    assert "--yolo" in args
    assert "--resume" not in args                          # stateless
    assert args[-2:] == ["--prompt", "hello"]


@pytest.mark.ci
def test_build_args_stream_uses_stream_json(bob_present):
    p = BobCliProvider(_cfg())
    args = p._build_args("hi", stream=True)
    assert args[args.index("--output-format") + 1] == "stream-json"


@pytest.mark.ci
def test_build_args_non_premium_model_adds_model_flag(bob_present):
    p = BobCliProvider(_cfg(model="some-model"))
    args = p._build_args("hi")
    assert args[args.index("--model") + 1] == "some-model"
    # "premium" is Bob's default tier and must NOT be passed as --model
    p2 = BobCliProvider(_cfg(model="premium"))
    assert "--model" not in p2._build_args("hi")


@pytest.mark.ci
def test_build_args_stateful_resumes_after_first_call(bob_present):
    p = BobCliProvider(_cfg())
    p.configure(repo_dir="/repo", stateful=True, chat_mode="code")
    # First call: no session yet → no --resume
    assert "--resume" not in p._build_args("first")
    # Simulate a completed turn that captured a session id
    p._session_id = "sess-123"
    p._call_count = 1
    args = p._build_args("second")
    assert args[args.index("--resume") + 1] == "sess-123"
    assert "code" in args   # configure() overrode the chat mode


# ── configure / session lifecycle ────────────────────────────────────────────

@pytest.mark.ci
def test_configure_and_new_session(bob_present):
    p = BobCliProvider(_cfg())
    assert p._stateful is False                 # MCP default
    p.configure(repo_dir="/repo", system_prompt="ctx", stateful=True)
    assert p._stateful is True
    assert p._repo_dir == "/repo"
    p._session_id, p._call_count = "s", 4
    p.new_session()
    assert p._session_id is None and p._call_count == 0


# ── complete() ───────────────────────────────────────────────────────────────

@pytest.mark.ci
def test_complete_success(bob_present, monkeypatch):
    captured = {}

    def fake_run(args, **kw):
        captured["args"] = args
        captured["cwd"] = kw.get("cwd")
        return _FakeCompleted(returncode=0, stdout="  the answer  ")

    monkeypatch.setattr(bob_mod.subprocess, "run", fake_run)
    p = BobCliProvider(_cfg())
    p.configure(repo_dir="/repo", stateful=True)
    out = p.complete("question")
    assert out == "the answer"                  # stripped
    assert p._call_count == 1
    assert captured["cwd"] == "/repo"
    assert "--prompt" in captured["args"]


@pytest.mark.ci
def test_complete_extracts_session_and_result_from_json(bob_present, monkeypatch):
    monkeypatch.setattr(
        bob_mod.subprocess, "run",
        lambda args, **kw: _FakeCompleted(
            returncode=0, stdout='{"session_id": "abc-9", "result": "done"}'),
    )
    p = BobCliProvider(_cfg())
    out = p.complete("q")
    assert out == "done"
    assert p._session_id == "abc-9"


@pytest.mark.ci
def test_complete_nonzero_exit_raises_runtimeerror(bob_present, monkeypatch):
    monkeypatch.setattr(
        bob_mod.subprocess, "run",
        lambda args, **kw: _FakeCompleted(returncode=2, stderr="kaboom"),
    )
    p = BobCliProvider(_cfg())
    with pytest.raises(RuntimeError, match="bob exited 2"):
        p.complete("q")


@pytest.mark.ci
def test_complete_timeout_raises_aitimeouterror(bob_present, monkeypatch):
    def fake_run(args, **kw):
        raise subprocess.TimeoutExpired(cmd=args, timeout=kw.get("timeout", 1))

    monkeypatch.setattr(bob_mod.subprocess, "run", fake_run)
    p = BobCliProvider(_cfg())
    with pytest.raises(AITimeoutError):
        p.complete("q")


@pytest.mark.ci
def test_complete_missing_binary_raises(monkeypatch):
    monkeypatch.setattr(bob_mod.shutil, "which", lambda name: None)
    p = BobCliProvider(_cfg())
    with pytest.raises(RuntimeError, match="not found"):
        p.complete("q")


# ── factory dispatch ─────────────────────────────────────────────────────────

@pytest.mark.ci
def test_factory_returns_bob_provider(bob_present):
    from jsat._ai import get_ai_provider
    p = get_ai_provider(_cfg(provider="bob_cli"))
    assert isinstance(p, BobCliProvider)
    assert p.provider_name == "bob_cli"


# ── model / config layer ─────────────────────────────────────────────────────

@pytest.mark.ci
def test_aiconfig_accepts_bob_cli():
    from jsat._models import AIConfig
    cfg = AIConfig(provider="bob_cli", model="premium")
    assert cfg.provider == "bob_cli"


@pytest.mark.ci
def test_provider_reachable_bob(monkeypatch):
    import shutil as _sh

    import jsat._config as cfgmod
    monkeypatch.setattr(_sh, "which",
                        lambda name: "/fake/bin/bob" if name == "bob" else None)
    assert cfgmod._provider_reachable("bob_cli", None) is True
    monkeypatch.setattr(_sh, "which", lambda name: None)
    assert cfgmod._provider_reachable("bob_cli", None) is False


@pytest.mark.ci
def test_detect_ai_providers_includes_bob_and_ranks_after_claude(monkeypatch):
    import shutil as _sh

    import jsat._config as cfgmod
    # Both CLIs present; no API keys / local servers.
    monkeypatch.setattr(_sh, "which",
                        lambda name: f"/fake/bin/{name}" if name in ("claude", "bob") else None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    results = cfgmod.detect_ai_providers(None)
    keys = [r["provider_key"] for r in results]
    assert "bob_cli" in keys
    bob = next(r for r in results if r["provider_key"] == "bob_cli")
    assert bob["available"] is True
    assert bob["alias"] == "bob"
    # Documented priority: Claude CLI ranks ahead of Bob CLI.
    assert keys.index("claude_cli") < keys.index("bob_cli")


# ── shell launcher ───────────────────────────────────────────────────────────

@pytest.mark.ci
def test_launch_bob_is_clean_interactive(monkeypatch, tmp_path):
    """`jsat bob` must launch a clean INTERACTIVE session: no positional prompt
    and no -i/--prompt-interactive injection (which would burn a turn on a
    useless acknowledgement). JSAT tools/guidance come from .bob/ + BOB.md."""
    import shutil as _sh

    from jsat.tools import shell as shellmod

    # .bob/settings.json present so no "not connected" warning path is exercised.
    (tmp_path / ".bob").mkdir()
    (tmp_path / ".bob" / "settings.json").write_text("{}")

    captured = {}
    # launch_ai_with_jsat_tools does `import shutil`/`import subprocess` locally,
    # so patch the real modules (picked up from sys.modules).
    monkeypatch.setattr(_sh, "which", lambda name: f"/fake/bin/{name}")

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        captured["cwd"] = kw.get("cwd")
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    fake_jsat = types.SimpleNamespace(
        _repo=str(tmp_path),
        index_status={"nodes": 10, "edges": 20},
    )
    shellmod.launch_ai_with_jsat_tools(fake_jsat, ai="bob", mode="advanced")

    cmd = captured["cmd"]
    assert cmd[0] == "bob"
    assert "--yolo" in cmd
    assert cmd[cmd.index("--chat-mode") + 1] == "advanced"
    # No prompt injection of any kind.
    assert "--prompt-interactive" not in cmd
    assert "--prompt" not in cmd
    # No trailing positional prompt: the last token is a flag or its value.
    assert cmd[-1] in ("--yolo", "advanced")
    assert captured["cwd"] == str(tmp_path)


@pytest.mark.ci
def test_launch_bob_resume_passthrough(monkeypatch, tmp_path):
    import shutil as _sh

    from jsat.tools import shell as shellmod

    (tmp_path / ".bob").mkdir()
    (tmp_path / ".bob" / "settings.json").write_text("{}")

    captured = {}
    monkeypatch.setattr(_sh, "which", lambda name: f"/fake/bin/{name}")
    monkeypatch.setattr(
        subprocess, "run",
        lambda cmd, **kw: captured.update(cmd=cmd) or _FakeCompleted())

    fake_jsat = types.SimpleNamespace(_repo=str(tmp_path),
                                      index_status={"nodes": 0, "edges": 0})
    shellmod.launch_ai_with_jsat_tools(fake_jsat, ai="bob", resume="sess-42")
    assert captured["cmd"][captured["cmd"].index("--resume") + 1] == "sess-42"

    shellmod.launch_ai_with_jsat_tools(fake_jsat, ai="bob", continue_session=True)
    assert captured["cmd"][captured["cmd"].index("--resume") + 1] == "latest"


# ── /jsat-* slash commands for Bob ───────────────────────────────────────────

@pytest.mark.ci
def test_write_bob_commands_creates_one_file_per_skill(tmp_path):
    from jsat.cli import _JSAT_SKILLS, _write_bob_commands

    out = _write_bob_commands("project", commands_dir=tmp_path / ".bob" / "commands")
    files = sorted(p.name for p in out.glob("*.md"))
    assert files == sorted(f"{name}.md" for name in _JSAT_SKILLS)
    # Filename (sans .md) is the command name → /jsat-query etc.
    assert "jsat-query.md" in files


@pytest.mark.ci
def test_write_bob_commands_rewrites_arguments_placeholder(tmp_path):
    from jsat.cli import _write_bob_commands

    out = _write_bob_commands("project", commands_dir=tmp_path)
    # Claude's $ARGUMENTS must not leak into Bob commands (Bob uses $@).
    for md in out.glob("*.md"):
        assert "$ARGUMENTS" not in md.read_text()

    query = (out / "jsat-query.md").read_text()
    assert 'question="$@"' in query
    # Frontmatter present; commands that take input advertise an argument-hint.
    assert query.startswith("---\ndescription:")
    assert "argument-hint:" in query and "<arguments>" in query

    # A no-argument command gets no argument-hint.
    services = (out / "jsat-list-services.md").read_text()
    assert "argument-hint" not in services


@pytest.mark.ci
def test_write_bob_commands_frontmatter_is_valid_yaml(tmp_path):
    """Bob parses frontmatter as strict YAML — descriptions with ':' (e.g.
    jsat-crack: 'war room: architect, ...') must be quoted, not break parsing."""
    yaml = pytest.importorskip("yaml")
    from jsat.cli import _write_bob_commands

    out = _write_bob_commands("project", commands_dir=tmp_path)
    for md in out.glob("*.md"):
        text = md.read_text()
        assert text.startswith("---\n")
        frontmatter = text.split("---\n", 2)[1]
        data = yaml.safe_load(frontmatter)   # raises if invalid
        assert isinstance(data, dict) and data.get("description")

    crack = (out / "jsat-crack.md").read_text()
    assert 'description: "' in crack        # colon-containing desc is quoted


@pytest.mark.ci
def test_commands_carry_answer_directive(tmp_path):
    """Every generated command must tell the assistant to deliver a real answer
    from the tool result, not just echo raw tool output."""
    from jsat.cli import _JSAT_CMD_DIRECTIVE, _write_bob_commands, _write_jsat_skills

    bob = _write_bob_commands("project", commands_dir=tmp_path / "bob")
    claude = _write_jsat_skills("project", commands_dir=tmp_path / "claude")
    for out in (bob, claude):
        for md in out.glob("*.md"):
            assert _JSAT_CMD_DIRECTIVE.strip() in md.read_text()


@pytest.mark.ci
def test_jsat_prompt_optimizes_then_answers(tmp_path):
    """/jsat-prompt must chain the optimized prompt into jsat__query by default,
    with an --optimize-only escape hatch."""
    from jsat.cli import _write_bob_commands

    out = _write_bob_commands("project", commands_dir=tmp_path)
    body = (out / "jsat-prompt.md").read_text()
    assert "jsat__query" in body            # it answers, not just optimizes
    assert "--optimize-only" in body        # opt-out to only show the rewrite


@pytest.mark.ci
def test_write_bob_commands_global_scope_defaults_home(monkeypatch, tmp_path):
    import jsat.cli as climod

    monkeypatch.setattr(climod.Path, "home", classmethod(lambda cls: tmp_path))
    out = climod._write_bob_commands("global")
    assert out == tmp_path / ".bob" / "commands"
    assert (out / "jsat-query.md").exists()
