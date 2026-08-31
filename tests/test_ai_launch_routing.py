"""Regression tests for native-tool and Ollama launch provider isolation."""
from __future__ import annotations

import json
import subprocess
import sys
import types

import pytest

from jsat._ai.routing import (
    apply_launch_ai_context,
    detect_launch_ai_context,
    explicit_provider_context,
    resolve_process_ai_context,
)


@pytest.mark.ci
@pytest.mark.parametrize("model", ["gemma4:31b-cloud", "qwen3:8b"])
def test_opencode_ollama_launch_uses_exact_selected_model(model: str) -> None:
    content = json.dumps({
        "provider": {"ollama": {"options": {"baseURL": "http://localhost:11434/v1"}}},
        "model": f"ollama/{model}",
    })
    context = detect_launch_ai_context({"OPENCODE_CONFIG_CONTENT": content})
    assert context is not None
    assert (context.provider, context.model) == ("ollama", model)
    assert context.base_url == "http://localhost:11434"
    assert context.source == "ollama-opencode"


@pytest.mark.ci
@pytest.mark.parametrize("model", ["gemma4:31b-cloud", "qwen3:8b"])
def test_claude_ollama_launch_uses_exact_selected_model(model: str) -> None:
    context = detect_launch_ai_context({
        "ANTHROPIC_BASE_URL": "http://localhost:11434",
        "ANTHROPIC_AUTH_TOKEN": "ollama",
        "ANTHROPIC_DEFAULT_SONNET_MODEL": model,
    })
    assert context is not None
    assert (context.provider, context.model) == ("ollama", model)
    assert context.base_url == "http://localhost:11434"
    assert context.source == "ollama-claude"


@pytest.mark.ci
def test_claude_ollama_launch_detected_without_documented_model_env_var() -> None:
    # `ollama launch claude` only documents ANTHROPIC_BASE_URL, ANTHROPIC_AUTH_TOKEN,
    # and ANTHROPIC_API_KEY (docs.ollama.com/integrations/claude-code) — no env var
    # carries the selected model. Detection must not require one.
    context = detect_launch_ai_context({
        "ANTHROPIC_BASE_URL": "http://localhost:11434",
        "ANTHROPIC_AUTH_TOKEN": "ollama",
    })
    assert context is not None
    assert (context.provider, context.model) == ("ollama", None)
    assert context.source == "ollama-claude"


@pytest.mark.ci
def test_native_connectors_replace_stale_ollama_model() -> None:
    assert explicit_provider_context({"JSAT_AI_PROVIDER": "claude_cli"}).model is None
    assert explicit_provider_context({"JSAT_AI_PROVIDER": "codex_cli"}).model is None
    assert explicit_provider_context({"JSAT_AI_PROVIDER": "opencode_cli"}).model is None


@pytest.mark.ci
def test_native_connector_uses_only_an_explicit_model() -> None:
    context = explicit_provider_context({
        "JSAT_AI_PROVIDER": "codex_cli",
        "JSAT_AI_MODEL": "user-selected-model",
    })
    assert context is not None
    assert context.model == "user-selected-model"


@pytest.mark.ci
def test_native_connector_clears_model_from_previous_provider() -> None:
    from jsat._models import AIConfig

    stale = AIConfig(provider="ollama", model="old-ollama-model")
    context = explicit_provider_context({"JSAT_AI_PROVIDER": "codex_cli"})
    assert context is not None
    resolved = apply_launch_ai_context(stale, context)
    assert resolved.provider == "codex_cli"
    assert resolved.model is None


@pytest.mark.ci
def test_launch_context_clears_all_stale_provider_owned_fields() -> None:
    from jsat._models import AIConfig

    stale = AIConfig(
        provider="openai_compat",
        model="old-model",
        base_url="http://stale.example/v1",
        api_key_env="STALE_API_KEY",
    )
    context = explicit_provider_context({"JSAT_AI_PROVIDER": "codex_cli"})
    assert context is not None

    resolved = apply_launch_ai_context(stale, context)

    assert resolved.provider == "codex_cli"
    assert resolved.model is None
    assert resolved.base_url is None
    assert resolved.api_key_env is None


@pytest.mark.ci
def test_ollama_launch_context_replaces_stale_base_url() -> None:
    from jsat._ai.routing import LaunchAIContext
    from jsat._models import AIConfig

    stale = AIConfig(provider="openai_compat", base_url="http://stale.example/v1")
    context = LaunchAIContext("ollama", "selected", "http://localhost:11434")

    resolved = apply_launch_ai_context(stale, context)

    assert resolved.base_url == "http://localhost:11434"


@pytest.mark.ci
def test_ollama_launch_context_is_distinct_from_native_connector() -> None:
    env = {
        "JSAT_AI_PROVIDER": "opencode_cli",
        "OPENCODE_CONFIG_CONTENT": json.dumps({
            "provider": {"ollama": {"options": {"baseURL": "http://127.0.0.1:11434/v1"}}},
            "model": "ollama/gemma4:31b-cloud",
        }),
    }
    assert detect_launch_ai_context(env).provider == "ollama"
    assert explicit_provider_context(env).provider == "opencode_cli"
    assert resolve_process_ai_context(env).provider == "ollama"


@pytest.mark.ci
def test_invalid_or_unrelated_opencode_config_is_not_ollama_launch() -> None:
    assert detect_launch_ai_context({"OPENCODE_CONFIG_CONTENT": "not-json"}) is None
    assert detect_launch_ai_context({
        "OPENCODE_CONFIG_CONTENT": json.dumps({"model": "anthropic/claude-sonnet"})
    }) is None


@pytest.mark.ci
def test_opencode_cli_provider_disables_recursive_jsat_mcp(monkeypatch, tmp_path) -> None:
    import jsat._ai.opencode_cli as provider_module

    monkeypatch.setattr(provider_module, "_find_opencode", lambda: "/fake/bin/opencode")
    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        captured.update(cmd=cmd, cwd=kwargs.get("cwd"), env=kwargs.get("env"))
        return subprocess.CompletedProcess(cmd, 0, stdout="answer\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    cfg = types.SimpleNamespace(ai=types.SimpleNamespace(model="default", timeout_seconds=30))
    provider = provider_module.OpenCodeCliProvider(cfg)
    provider.configure(repo_dir=str(tmp_path))
    assert provider.complete("explain this") == "answer"
    assert captured["cmd"] == ["/fake/bin/opencode", "run", "explain this"]
    assert captured["cwd"] == str(tmp_path)
    inline = json.loads(captured["env"]["OPENCODE_CONFIG_CONTENT"])
    assert inline["mcp"]["jsat"] == {"enabled": False}


@pytest.mark.ci
def test_opencode_cli_passes_only_provider_qualified_model(monkeypatch) -> None:
    import jsat._ai.opencode_cli as provider_module

    monkeypatch.setattr(provider_module, "_find_opencode", lambda: "/fake/bin/opencode")
    cfg = types.SimpleNamespace(
        ai=types.SimpleNamespace(model="ollama/qwen3:8b", timeout_seconds=30)
    )
    provider = provider_module.OpenCodeCliProvider(cfg)
    assert provider._build_args("hello") == [
        "/fake/bin/opencode", "run", "hello", "--model", "ollama/qwen3:8b"
    ]


@pytest.mark.ci
def test_codex_cli_omits_model_when_client_owns_selection(monkeypatch) -> None:
    import jsat._ai.codex_cli as provider_module

    monkeypatch.setattr(provider_module.shutil, "which", lambda _: "/fake/bin/codex")
    cfg = types.SimpleNamespace(ai=types.SimpleNamespace(model=None, timeout_seconds=30))
    provider = provider_module.CodexCliProvider(cfg)
    assert "--model" not in provider._build_args()


@pytest.mark.ci
def test_codex_failure_explains_model_selection(monkeypatch) -> None:
    import jsat._ai.codex_cli as provider_module

    monkeypatch.setattr(provider_module.shutil, "which", lambda _: "/fake/bin/codex")
    monkeypatch.setattr(
        provider_module.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 1, "", "invalid model"),
    )
    cfg = types.SimpleNamespace(ai=types.SimpleNamespace(model=None, timeout_seconds=30))
    provider = provider_module.CodexCliProvider(cfg)
    with pytest.raises(RuntimeError) as exc:
        provider.complete("hello")
    assert "use its model selector" in str(exc.value)
    assert "Omit JSAT's model setting" in str(exc.value)


@pytest.mark.ci
def test_ollama_provider_needs_only_running_http_server(monkeypatch) -> None:
    from jsat._ai.ollama import OllamaProvider, _HttpOllamaClient

    monkeypatch.setitem(sys.modules, "ollama", None)
    cfg = types.SimpleNamespace(ai=types.SimpleNamespace(
        model="gemma4:31b-cloud",
        base_url="http://localhost:11434",
        max_tokens=100,
        timeout_seconds=30,
    ))
    provider = OllamaProvider(cfg)
    assert isinstance(provider._client, _HttpOllamaClient)
    assert provider.model_name == "gemma4:31b-cloud"


@pytest.mark.ci
def test_http_ollama_client_requests_one_json_response(monkeypatch) -> None:
    import httpx

    from jsat._ai.ollama import _HttpOllamaClient

    captured: dict[str, object] = {}

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"response": "answer"}

    def fake_post(url, **kwargs):
        captured.update(url=url, json=kwargs["json"])
        return Response()

    monkeypatch.setattr(httpx, "post", fake_post)
    client = _HttpOllamaClient("http://localhost:11434", 30)
    result = client.generate(model="qwen3:8b", prompt="hello")

    assert result == {"response": "answer"}
    assert captured["json"]["stream"] is False


@pytest.mark.ci
def test_switch_ai_clears_previous_provider_url_and_key(monkeypatch) -> None:
    from jsat._core import JSAT
    from jsat._models import AIConfig, JSATConfig

    class AvailableAI:
        def is_available(self): return True

    js = JSAT.__new__(JSAT)
    js._cfg = JSATConfig(ai=AIConfig(
        provider="openai_compat",
        model="old-model",
        base_url="http://stale.example/v1",
        api_key_env="STALE_KEY",
    ))
    monkeypatch.setattr(js, "_get_ai", lambda: AvailableAI())

    provider, model, reachable = js.switch_ai("codex")

    assert (provider, model, reachable) == ("codex", None, True)
    assert js._cfg.ai.base_url is None
    assert js._cfg.ai.api_key_env is None


@pytest.mark.ci
def test_switch_ai_requires_model_when_provider_does_not_own_selection() -> None:
    from jsat._core import JSAT
    from jsat._models import JSATConfig

    js = JSAT.__new__(JSAT)
    js._cfg = JSATConfig()

    with pytest.raises(ValueError, match="No model selected") as exc:
        js.switch_ai("phi")

    assert "jsat ai models ollama" in str(exc.value)


@pytest.mark.ci
def test_ollama_availability_requires_selected_registered_model(monkeypatch) -> None:
    import httpx

    from jsat._ai.ollama import OllamaProvider

    class Response:
        status_code = 200
        def json(self): return {"models": [{"name": "registered:latest"}]}

    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: Response())
    cfg = types.SimpleNamespace(ai=types.SimpleNamespace(
        model="missing",
        base_url="http://localhost:11434",
        max_tokens=100,
        timeout_seconds=30,
    ))

    assert OllamaProvider(cfg).is_available() is False
