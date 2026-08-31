"""Tests for jsat._ai.aliases and the CLI error paths that use it.

Regression cover for names JSAT documents but used to reject:
`jsat ai use claude_cli`, `jsat ai use gpt`, `jsat ai use bob`, and for the
provider/tool confusion in `jsat connect <provider>`.
"""
from __future__ import annotations

import pytest
from typer.testing import CliRunner

from jsat._ai.aliases import (
    MCP_TOOLS,
    alias_names,
    is_provider_alias,
    normalize_alias,
    provider_aliases,
    resolve_alias,
    suggest,
)
from jsat.cli import app  # imports every _cli_* module, registering all subcommands

runner = CliRunner()


# ── normalization ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw", ["claude_cli", "claude-cli", "CLAUDE_CLI", "  Claude-CLI  "])
def test_normalize_collapses_case_space_and_underscore(raw: str) -> None:
    assert normalize_alias(raw) == "claude-cli"


def test_underscore_and_hyphen_resolve_identically() -> None:
    assert resolve_alias("claude_cli") == resolve_alias("claude-cli")
    assert resolve_alias("lm_studio") == resolve_alias("lm-studio")


# ── alias resolution ──────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("alias", "expected_provider"),
    [
        ("claude_cli", "claude_cli"),
        ("claude-cli", "claude_cli"),
        ("anthropic", "anthropic"),
        ("haiku", "anthropic"),
        ("opus", "anthropic"),
        ("bob", "bob_cli"),
        ("codex-cli", "codex_cli"),
        ("opencode", "opencode_cli"),
        ("opencode-cli", "opencode_cli"),
        ("gpt", "openai"),
        ("openai", "openai"),
        ("codex", "codex_cli"),
        ("ollama", "ollama"),
        ("phi", "ollama"),
        ("gemini", "openai_compat"),
        ("lmstudio", "openai_compat"),
    ],
)
def test_documented_aliases_resolve(alias: str, expected_provider: str) -> None:
    resolved = resolve_alias(alias)
    assert resolved is not None, f"{alias!r} should be a valid provider"
    assert resolved[0] == expected_provider


def test_unknown_alias_returns_none() -> None:
    assert resolve_alias("definitely-not-a-provider") is None


def test_custom_alias_honours_base_url() -> None:
    resolved = resolve_alias("custom", base_url="http://example.test/v1")
    assert resolved is not None
    assert resolved[2] == "http://example.test/v1"


def test_every_alias_has_provider_and_optional_model() -> None:
    for alias, (provider, model, _url, _key_env) in provider_aliases().items():
        assert provider, f"{alias} has no provider"
        assert model is None or model.strip(), f"{alias} has an invalid model"


@pytest.mark.ci
def test_provider_aliases_never_hard_code_a_model() -> None:
    assert all(
        model is None for _provider, model, _url, _key_env in provider_aliases().values()
    )


@pytest.mark.ci
@pytest.mark.parametrize(
    ("alias", "expected_key_env"),
    [
        ("gemini", "GEMINI_API_KEY"),
        ("gemini-pro", "GEMINI_API_KEY"),
        ("deepseek", "DEEPSEEK_API_KEY"),
        ("lmstudio", None),
        ("anthropic", None),
    ],
)
def test_alias_api_key_env_overrides_only_where_needed(alias, expected_key_env) -> None:
    resolved = resolve_alias(alias)
    assert resolved is not None
    assert resolved[3] == expected_key_env


@pytest.mark.ci
def test_deepseek_resolves_to_openai_compat_with_its_own_base_url() -> None:
    resolved = resolve_alias("deepseek")
    assert resolved is not None
    assert resolved[0] == "openai_compat"
    assert resolved[2] == "https://api.deepseek.com/v1"


def test_provider_and_tool_namespaces_are_distinguishable() -> None:
    assert is_provider_alias("ollama")
    assert not is_provider_alias("cursor")
    # Some names legitimately select both a provider and a connection target.
    assert is_provider_alias("claude") and "claude" in MCP_TOOLS
    assert is_provider_alias("opencode") and "opencode" in MCP_TOOLS
    assert "ollama" in MCP_TOOLS


def test_suggest_finds_near_miss() -> None:
    assert suggest("ollam", alias_names()) == ["ollama"]
    assert suggest("cursr", MCP_TOOLS) == ["cursor"]


# ── SDK switch_ai shares the same table ───────────────────────────────────────

def test_switch_ai_rejects_unknown_provider_with_list() -> None:
    from jsat._core import JSAT

    js = JSAT.__new__(JSAT)  # no repo/config work needed for alias validation
    with pytest.raises(ValueError, match="Unknown provider"):
        js.switch_ai("not-a-provider")


# ── CLI error paths ───────────────────────────────────────────────────────────

def test_unknown_connect_target_is_intercepted_not_left_to_typer() -> None:
    """Regression, behavioural so it holds on any typer version.

    typer >=0.27 vendors click, and `typer._click.UsageError` is a DIFFERENT class
    from `click.UsageError`. Catching only the latter meant `jsat connect ollama`
    fell through to a bare Typer error on the real CLI — while CliRunner under an
    older typer (which reaches real click) kept passing. Assert the interception
    itself rather than any class identity.
    """
    import click
    import typer
    import typer.main

    group = typer.main.get_command(app).commands["connect"]  # type: ignore[attr-defined]
    ctx = click.Context(group, info_name="connect")

    with pytest.raises(typer.Exit) as exc:
        group.resolve_command(ctx, ["definitely-not-a-tool"])
    assert exc.value.exit_code == 1


def test_usage_error_catch_includes_every_available_usage_error() -> None:
    import click

    from jsat._cli_common import _usage_errors

    caught = _usage_errors()
    assert click.exceptions.UsageError in caught
    try:
        from typer._click.exceptions import UsageError as vendored
    except Exception:
        return  # this typer version does not vendor click — nothing more to assert
    assert vendored in caught


def test_connect_with_non_tool_provider_name_redirects_to_ai_use() -> None:
    result = runner.invoke(app, ["connect", "phi"])
    assert result.exit_code == 1
    assert "jsat ai use phi" in result.output
    assert "list" not in result.output.split("Connectable tools:")[-1]


def test_connect_typo_suggests_closest_tool() -> None:
    result = runner.invoke(app, ["connect", "claud"])
    assert result.exit_code == 1
    assert "jsat connect claude" in result.output


def test_ai_use_with_tool_name_redirects_to_connect() -> None:
    result = runner.invoke(app, ["ai", "use", "cursor"])
    assert result.exit_code == 1
    assert "jsat connect cursor" in result.output


def test_ai_use_typo_suggests_closest_provider() -> None:
    result = runner.invoke(app, ["ai", "use", "ollam"])
    assert result.exit_code == 1
    assert "ollama" in result.output


@pytest.mark.ci
@pytest.mark.parametrize("alias", ["phi", "llama"])
def test_ollama_model_family_alias_requires_explicit_model(alias: str) -> None:
    result = runner.invoke(app, ["ai", "use", alias])

    assert result.exit_code == 1
    assert "model family" in result.output
    assert f"jsat ai use {alias} --model <model>" in result.output


@pytest.mark.ci
def test_ai_use_clears_settings_owned_by_previous_provider(monkeypatch, tmp_path) -> None:
    import yaml

    from jsat._core import JSAT

    class AvailableAI:
        def is_available(self): return True

    config = tmp_path / "config.yaml"
    config.write_text(
        "ai:\n"
        "  provider: openai_compat\n"
        "  model: stale-model\n"
        "  base_url: http://stale.example/v1\n"
        "  api_key_env: STALE_KEY\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(JSAT, "_get_ai", lambda self: AvailableAI())

    result = runner.invoke(
        app,
        ["ai", "use", "codex-cli", "--config", str(config)],
    )

    assert result.exit_code == 0
    ai = yaml.safe_load(config.read_text(encoding="utf-8"))["ai"]
    assert ai == {"provider": "codex_cli"}


@pytest.mark.ci
@pytest.mark.parametrize(
    ("alias", "model", "expected_key_env"),
    [
        ("gemini", "gemini-1.5-flash", "GEMINI_API_KEY"),
        ("deepseek", "deepseek-chat", "DEEPSEEK_API_KEY"),
    ],
)
def test_ai_use_persists_the_resolved_api_key_env(
    monkeypatch, tmp_path, alias, model, expected_key_env
) -> None:
    """Regression: api_key_env used to be unconditionally cleared on every switch,
    so GEMINI_API_KEY (and now DEEPSEEK_API_KEY) never actually reached the runtime
    openai_compat provider."""
    import yaml

    from jsat._core import JSAT

    class AvailableAI:
        def is_available(self): return True

    config = tmp_path / "config.yaml"
    monkeypatch.setattr(JSAT, "_get_ai", lambda self: AvailableAI())

    result = runner.invoke(
        app,
        ["ai", "use", alias, "--model", model, "--config", str(config)],
    )

    assert result.exit_code == 0
    ai = yaml.safe_load(config.read_text(encoding="utf-8"))["ai"]
    assert ai["api_key_env"] == expected_key_env


def test_disconnect_with_non_tool_provider_name_is_explained() -> None:
    result = runner.invoke(app, ["disconnect", "phi"])
    assert result.exit_code == 1
    assert "AI provider" in result.output
